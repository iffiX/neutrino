#!/usr/bin/env bash
# A Mac. Its own script rather than a flag on up.sh because of what it costs:
# a Mac runs on a dedicated host, and allocating one bills 24 hours whether
# the instance lives for two or for all of them. Nothing here runs by
# accident on the way to something else.
#
#   macos/up.sh          allocate the host, launch macOS on it, wait for SSH
#
# The hub from up.sh must already be there: the Mac joins it.

source "$(dirname "$0")/../common.sh"

# The M1: the cheapest Apple silicon host, and arm64 is the only macOS the
# client is built for.
MAC_TYPE="${MAC_TYPE:-mac2.metal}"
ZONE="${ZONE:-us-east-1a}"
# Amazon's own macOS images, newest first; arm64_mac is the Apple silicon one.
MAC_AMI_FILTER="${MAC_AMI_FILTER:-amzn-ec2-macos-15*}"

[ -n "$(hub_ip)" ] || { echo "no hub in state/; run up.sh first" >&2; exit 1; }
SG_ID="$(state sg_id)"
[ -n "$SG_ID" ] || { echo "no security group in state/; run up.sh first" >&2; exit 1; }

echo "== dedicated host ($MAC_TYPE in $ZONE)"
HOST_ID="$(aws ec2 describe-hosts --filter "Name=tag:project,Values=$NAME" \
    "Name=instance-type,Values=$MAC_TYPE" \
    --query 'Hosts[?State==`available` || State==`pending`].HostId | [0]' --output text 2>/dev/null || true)"
if [ -z "$HOST_ID" ] || [ "$HOST_ID" = None ]; then
    HOST_ID="$(aws ec2 allocate-hosts --instance-type "$MAC_TYPE" \
        --availability-zone "$ZONE" --quantity 1 --auto-placement off \
        --tag-specifications "ResourceType=dedicated-host,Tags=[{Key=Name,Value=$NAME-mac},{Key=project,Value=$NAME}]" \
        --query 'HostIds[0]' --output text)"
    echo "   allocated $HOST_ID: 24 hours are now billed whatever happens next"
else
    echo "   reusing $HOST_ID"
fi
echo "$HOST_ID" > "$STATE/mac_host_id"

echo "== image"
MAC_AMI="$(aws ec2 describe-images --owners amazon \
    --filters "Name=name,Values=$MAC_AMI_FILTER" Name=architecture,Values=arm64_mac \
    --query 'reverse(sort_by(Images,&CreationDate))[0].[ImageId,Name]' --output text)"
echo "   $MAC_AMI"
MAC_AMI="${MAC_AMI%%	*}"

SUBNET_ID="$(aws ec2 describe-subnets \
    --filters Name=default-for-az,Values=true "Name=availability-zone,Values=$ZONE" \
    --query 'Subnets[0].SubnetId' --output text)"

echo "== instance"
MAC_ID="$(aws ec2 describe-instances \
    --filters "Name=tag:Name,Values=$NAME-mac" "Name=instance-state-name,Values=pending,running" \
    --query 'Reservations[0].Instances[0].InstanceId' --output text 2>/dev/null || true)"
if [ -z "$MAC_ID" ] || [ "$MAC_ID" = None ]; then
    MAC_ID="$(aws ec2 run-instances --image-id "$MAC_AMI" --instance-type "$MAC_TYPE" \
        --key-name "$NAME-rsa" --security-group-ids "$SG_ID" --subnet-id "$SUBNET_ID" \
        --placement "HostId=$HOST_ID,Tenancy=host" \
        --tag-specifications "ResourceType=instance,Tags=[{Key=Name,Value=$NAME-mac},{Key=project,Value=$NAME}]" \
        --query 'Instances[0].InstanceId' --output text)"
fi
echo "$MAC_ID" > "$STATE/mac_id"
echo "   $MAC_ID"

echo "== waiting for it to run (a Mac takes a while to boot)"
aws ec2 wait instance-running --instance-ids "$MAC_ID"
aws ec2 describe-instances --instance-ids "$MAC_ID" \
    --query 'Reservations[0].Instances[0].PublicIpAddress' --output text > "$STATE/mac_ip"
aws ec2 describe-instances --instance-ids "$MAC_ID" \
    --query 'Reservations[0].Instances[0].PrivateIpAddress' --output text > "$STATE/mac_private_ip"
echo "   mac  $(mac_ip)  (private $(state mac_private_ip))"

echo "== waiting for SSH"
printf '   mac '
wait_ssh "$MAC_USER" "$(mac_ip)" 120
echo "up. Next: macos/push.sh, then macos/test.sh"
