#!/usr/bin/env bash
# What this harness has running, and roughly for how long. The answer to
# "is anything still billing" before walking away.

source "$(dirname "$0")/common.sh"

echo "instances:"
aws ec2 describe-instances --filters "Name=tag:project,Values=$NAME" \
    --query 'Reservations[].Instances[?State.Name!=`terminated`].[Tags[?Key==`Name`]|[0].Value,InstanceId,InstanceType,State.Name,PublicIpAddress,LaunchTime]' \
    --output text | sed 's/^/   /'
echo "dedicated hosts:"
aws ec2 describe-hosts --filter "Name=tag:project,Values=$NAME" \
    --query 'Hosts[?State!=`released`].[HostId,InstanceType,State,AllocationTime]' \
    --output text | sed 's/^/   /'
echo "(empty lines above mean nothing is billing)"
