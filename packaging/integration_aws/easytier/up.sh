#!/usr/bin/env bash
# A private EasyTier rendezvous node on AWS: the public middle box two of our
# own machines meet through when the campus firewall lets neither of them
# accept an inbound connection. EasyTier ships no public shared node, so this
# is ours.
#
#   ./up.sh
#
# Rerunning is safe: an instance already up is kept, and the network name and
# secret are generated once into state/easytier_network and reused, so a
# second run leaves the same network standing.

source "$(dirname "$0")/lane.sh"

mkdir -p "$STATE"
[ -f "$KEY_FILE" ] || ssh-keygen -q -t ed25519 -N "" -C "$NAME" -f "$KEY_FILE"

echo "== key pair"
if ! aws ec2 describe-key-pairs --key-names "$NAME" >/dev/null 2>&1; then
    aws ec2 import-key-pair --key-name "$NAME" \
        --public-key-material "fileb://$KEY_FILE.pub" >/dev/null
fi
echo "   $NAME"

echo "== network credentials"
if [ ! -f "$ET_NETWORK_FILE" ]; then
    # Generated here, never on the node, and never passed through a command
    # line. A network is its name and its secret, and the secret is also the
    # key the members encrypt to each other with.
    (
        umask 077
        python3 - > "$ET_NETWORK_FILE" <<'PY'
import secrets

print(f"ET_NETWORK_NAME=neutrino-{secrets.token_hex(4)}")
print(f"ET_NETWORK_SECRET={secrets.token_urlsafe(24)}")
PY
    )
fi
chmod 600 "$ET_NETWORK_FILE"
echo "   $(et_network_name), secret in state/easytier_network"

echo "== security group"
MY_IP="$(curl -s -4 https://api.ipify.org)"
[ -n "$MY_IP" ] || { echo "could not learn this machine's address" >&2; exit 1; }
VPC_ID="$(aws ec2 describe-vpcs --filters Name=is-default,Values=true \
    --query 'Vpcs[0].VpcId' --output text)"
SG_ID="$(aws ec2 describe-security-groups --filters "Name=group-name,Values=$ET_NAME" \
    --query 'SecurityGroups[0].GroupId' --output text 2>/dev/null || true)"
if [ -z "$SG_ID" ] || [ "$SG_ID" = None ]; then
    SG_ID="$(aws ec2 create-security-group --group-name "$ET_NAME" \
        --description "neutrino integration: a private easytier rendezvous, open to one address" \
        --vpc-id "$VPC_ID" --query GroupId --output text)"
    aws ec2 create-tags --resources "$SG_ID" \
        --tags "Key=Name,Value=$ET_NAME" "Key=project,Value=$NAME" >/dev/null
fi
echo "$SG_ID" > "$STATE/easytier_sg_id"

# Its own group, and never 0.0.0.0/0 on any of it. A rendezvous node is
# reachable by definition, so the only thing keeping strangers off it is the
# source address: ours, and nothing else. `--private-mode true` on the node
# is the second answer, for anyone who reaches the port anyway.
allow() {
    local protocol="$1" port="$2" cidr="$3" reply
    if ! reply="$(aws ec2 authorize-security-group-ingress --group-id "$SG_ID" \
        --protocol "$protocol" --port "$port" --cidr "$cidr" 2>&1)"; then
        case "$reply" in
            *InvalidPermission.Duplicate*) ;;
            *) echo "$reply" >&2; return 1 ;;
        esac
    fi
}
# The shell is this machine's alone. The overlay port also answers the
# ranges in ET_PEER_CIDRS, which is how a test machine on a mobile network
# reaches the node without a new rule every time its address moves: the
# node still refuses anyone without the network name and secret.
allow tcp 22 "$MY_IP/32"
for cidr in "$MY_IP/32" ${ET_PEER_CIDRS:-}; do
    allow tcp "$ET_PORT" "$cidr"
    allow udp "$ET_PORT" "$cidr"
done
echo "   $SG_ID: tcp/22 from $MY_IP only, tcp+udp/$ET_PORT from $MY_IP ${ET_PEER_CIDRS:-}"

echo "== instance ($ET_TYPE, Debian 12)"
ET_ID="$(aws ec2 describe-instances \
    --filters "Name=tag:Name,Values=$ET_NAME" \
              "Name=instance-state-name,Values=pending,running" \
    --query 'Reservations[0].Instances[0].InstanceId' --output text 2>/dev/null || true)"
if [ -z "$ET_ID" ] || [ "$ET_ID" = None ]; then
    AMI="$(aws ssm get-parameter --name /aws/service/debian/release/12/latest/amd64 \
        --query Parameter.Value --output text)"
    SUBNET_ID="$(aws ec2 describe-subnets \
        --filters Name=default-for-az,Values=true "Name=availability-zone,Values=$ET_ZONE" \
        --query 'Subnets[0].SubnetId' --output text)"
    ET_ID="$(aws ec2 run-instances --image-id "$AMI" --instance-type "$ET_TYPE" \
        --key-name "$NAME" --security-group-ids "$SG_ID" --subnet-id "$SUBNET_ID" \
        --tag-specifications "ResourceType=instance,Tags=[{Key=Name,Value=$ET_NAME},{Key=project,Value=$NAME},{Key=lane,Value=$ET_ROLE}]" \
        --query 'Instances[0].InstanceId' --output text)"
fi
echo "$ET_ID" > "$STATE/easytier_id"
echo "   $ET_ID"

aws ec2 wait instance-running --instance-ids "$ET_ID"
aws ec2 describe-instances --instance-ids "$ET_ID" \
    --query 'Reservations[0].Instances[0].PublicIpAddress' --output text > "$STATE/easytier_ip"
echo "   $(et_ip)"

printf '== waiting for SSH '
wait_ssh "$ET_USER" "$(et_ip)"

echo "== installing $ET_VERSION"
scp_et "$LANE/install.sh" "$ET_USER@$(et_ip):/tmp/easytier_install.sh"
ssh_et "sudo bash /tmp/easytier_install.sh '$ET_URL' '$ET_SHA256' '$ET_UNIT' '$ET_PORT'" \
    | sed 's/^/   /'

echo "== network"
# Over the session's own stdin into a root-only file, so the secret is never
# an argument, never in a log, and never on the node's disk in the clear
# anywhere else.
ssh_et "sudo tee /etc/easytier/network.env > /dev/null" < "$ET_NETWORK_FILE"
ssh_et "sudo systemctl enable --now $ET_UNIT && sudo systemctl restart $ET_UNIT"
ssh_et "systemctl is-active $ET_UNIT" | sed 's/^/   /'

echo
echo "rendezvous  tcp://$(et_ip):$ET_PORT and udp://$(et_ip):$ET_PORT"
echo "network     $(et_network_name)  (secret in state/easytier_network)"
echo "next        ./verify.sh"
