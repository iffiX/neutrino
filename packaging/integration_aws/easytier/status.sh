#!/usr/bin/env bash
# What the rendezvous lane has running, what its group lets in, and what the
# node itself says it is connected to.

source "$(dirname "$0")/lane.sh"

echo "instance:"
aws ec2 describe-instances --filters "Name=tag:Name,Values=$ET_NAME" \
    --query 'Reservations[].Instances[?State.Name!=`terminated`].[InstanceId,InstanceType,State.Name,PublicIpAddress,LaunchTime]' \
    --output text | sed 's/^/   /'

echo "security group:"
aws ec2 describe-security-groups --filters "Name=group-name,Values=$ET_NAME" \
    --query 'SecurityGroups[0].IpPermissions[].[IpProtocol,FromPort,ToPort,IpRanges[0].CidrIp]' \
    --output text 2>/dev/null | sed 's/^/   /'

if [ -n "$(et_ip)" ]; then
    echo "node:"
    ssh_et "systemctl is-active $ET_UNIT; sudo easytier-cli peer" 2>/dev/null | sed 's/^/   /' \
        || echo "   unreachable"
fi
echo "(empty lines above mean nothing is billing)"
