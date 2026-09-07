#!/usr/bin/env bash
# Bring up the pair: a Debian 12 hub and a Windows Server 2025 device, in one
# security group that lets them talk and lets only this machine in.
#
#   ./up.sh              both
#   ./up.sh --no-windows the hub only
#
# Every id and address lands in state/, which is what every other script
# reads and what down.sh tears down. Rerunning is safe: what exists is kept.

source "$(dirname "$0")/common.sh"

WITH_WINDOWS=1
[ "${1:-}" = "--no-windows" ] && WITH_WINDOWS=0

HUB_TYPE="${HUB_TYPE:-t3.medium}"
WIN_TYPE="${WIN_TYPE:-t3.xlarge}"
ZONE="${ZONE:-us-east-1a}"

mkdir -p "$STATE"
[ -f "$KEY_FILE" ] || ssh-keygen -q -t ed25519 -N "" -C "$NAME" -f "$KEY_FILE"
[ -f "$RSA_KEY_FILE" ] || ssh-keygen -q -t rsa -b 4096 -N "" -C "$NAME" -f "$RSA_KEY_FILE"

echo "== key pairs"
if ! aws ec2 describe-key-pairs --key-names "$NAME" >/dev/null 2>&1; then
    aws ec2 import-key-pair --key-name "$NAME" \
        --public-key-material "fileb://$KEY_FILE.pub" >/dev/null
fi
if ! aws ec2 describe-key-pairs --key-names "$NAME-rsa" >/dev/null 2>&1; then
    aws ec2 import-key-pair --key-name "$NAME-rsa" \
        --public-key-material "fileb://$RSA_KEY_FILE.pub" >/dev/null
fi

echo "== security group"
MY_IP="$(curl -s -4 https://api.ipify.org)"
VPC_ID="$(aws ec2 describe-vpcs --filters Name=is-default,Values=true \
    --query 'Vpcs[0].VpcId' --output text)"
SG_ID="$(aws ec2 describe-security-groups --filters "Name=group-name,Values=$NAME" \
    --query 'SecurityGroups[0].GroupId' --output text 2>/dev/null || true)"
if [ -z "$SG_ID" ] || [ "$SG_ID" = None ]; then
    SG_ID="$(aws ec2 create-security-group --group-name "$NAME" \
        --description "neutrino integration: this machine in, the pair between themselves" \
        --vpc-id "$VPC_ID" --query GroupId --output text)"
    # This machine: SSH, RDP for a person, and the panel to look at.
    for port in 22 3389 "$PANEL_PORT"; do
        aws ec2 authorize-security-group-ingress --group-id "$SG_ID" \
            --protocol tcp --port "$port" --cidr "$MY_IP/32" >/dev/null
    done
    # The pair between themselves: the agent channel, the panel, whatever a
    # test declares.
    aws ec2 authorize-security-group-ingress --group-id "$SG_ID" \
        --protocol -1 --source-group "$SG_ID" >/dev/null
fi
echo "$SG_ID" > "$STATE/sg_id"
echo "   $SG_ID, open to $MY_IP"

SUBNET_ID="$(aws ec2 describe-subnets \
    --filters Name=default-for-az,Values=true "Name=availability-zone,Values=$ZONE" \
    --query 'Subnets[0].SubnetId' --output text)"

launch() {
    # launch <role> <ami> <type> <key pair> [extra run-instances args...]
    local role="$1" ami="$2" type="$3" key="$4"
    shift 4
    local existing
    existing="$(aws ec2 describe-instances \
        --filters "Name=tag:Name,Values=$NAME-$role" \
                  "Name=instance-state-name,Values=pending,running" \
        --query 'Reservations[0].Instances[0].InstanceId' --output text 2>/dev/null || true)"
    if [ -n "$existing" ] && [ "$existing" != None ]; then
        echo "$existing"
        return
    fi
    aws ec2 run-instances --image-id "$ami" --instance-type "$type" \
        --key-name "$key" --security-group-ids "$SG_ID" --subnet-id "$SUBNET_ID" \
        --tag-specifications "ResourceType=instance,Tags=[{Key=Name,Value=$NAME-$role},{Key=project,Value=$NAME}]" \
        --instance-initiated-shutdown-behavior terminate \
        "$@" --query 'Instances[0].InstanceId' --output text
}

echo "== hub ($HUB_TYPE, Debian 12)"
HUB_AMI="$(aws ssm get-parameter --name /aws/service/debian/release/12/latest/amd64 \
    --query Parameter.Value --output text)"
HUB_ID="$(launch hub "$HUB_AMI" "$HUB_TYPE" "$NAME")"
echo "$HUB_ID" > "$STATE/hub_id"
echo "   $HUB_ID"

if [ "$WITH_WINDOWS" = 1 ]; then
    echo "== windows ($WIN_TYPE, Windows Server 2025)"
    WIN_AMI_PARAMETER=/aws/service/ami-windows-latest/Windows_Server-2025-English-Full-Base  # scan: allow
    WIN_AMI="$(aws ssm get-parameter --name "$WIN_AMI_PARAMETER" \
        --query Parameter.Value --output text)"
    sed "s|@AUTHORIZED_KEY@|$(cat "$RSA_KEY_FILE.pub")|" "$HERE/windows/user_data.ps1" \
        > "$STATE/windows_user_data.ps1"
    WIN_ID="$(launch windows "$WIN_AMI" "$WIN_TYPE" "$NAME-rsa" \
        --user-data "file://$STATE/windows_user_data.ps1")"
    echo "$WIN_ID" > "$STATE/win_id"
    echo "   $WIN_ID"
fi

echo "== waiting for the instances to run"
IDS=("$HUB_ID")
[ "$WITH_WINDOWS" = 1 ] && IDS+=("$WIN_ID")
aws ec2 wait instance-running --instance-ids "${IDS[@]}"

address() {
    aws ec2 describe-instances --instance-ids "$1" \
        --query "Reservations[0].Instances[0].$2" --output text
}
address "$HUB_ID" PublicIpAddress > "$STATE/hub_ip"
address "$HUB_ID" PrivateIpAddress > "$STATE/hub_private_ip"
echo "   hub      $(hub_ip)  (private $(state hub_private_ip))"
if [ "$WITH_WINDOWS" = 1 ]; then
    address "$WIN_ID" PublicIpAddress > "$STATE/win_ip"
    address "$WIN_ID" PrivateIpAddress > "$STATE/win_private_ip"
    echo "   windows  $(win_ip)  (private $(state win_private_ip))"
fi

echo "== waiting for SSH"
printf '   hub     '
wait_ssh "$HUB_USER" "$(hub_ip)"
if [ "$WITH_WINDOWS" = 1 ]; then
    printf '   windows '
    wait_ssh "$WIN_USER" "$(win_ip)"
fi
echo "up. Next: linux/push_hub.sh, then windows/push.sh"
