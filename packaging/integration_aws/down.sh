#!/usr/bin/env bash
# Tear everything down and prove it: instances, dedicated hosts, the security
# group, the key pair. Found by tag rather than by state/, so a run whose
# state was lost is still cleaned up. Ends with status.sh, which must print
# nothing that bills.

source "$(dirname "$0")/common.sh"

echo "== instances"
IDS="$(aws ec2 describe-instances \
    --filters "Name=tag:project,Values=$NAME" \
              "Name=instance-state-name,Values=pending,running,stopping,stopped" \
    --query 'Reservations[].Instances[].InstanceId' --output text)"
if [ -n "$IDS" ]; then
    # shellcheck disable=SC2086
    aws ec2 terminate-instances --instance-ids $IDS \
        --query 'TerminatingInstances[].[InstanceId,CurrentState.Name]' --output text
    # shellcheck disable=SC2086
    aws ec2 wait instance-terminated --instance-ids $IDS
else
    echo "   none"
fi

echo "== dedicated hosts"
HOSTS="$(aws ec2 describe-hosts --filter "Name=tag:project,Values=$NAME" \
    --query 'Hosts[?State!=`released`].HostId' --output text)"
if [ -n "$HOSTS" ]; then
    # shellcheck disable=SC2086
    aws ec2 release-hosts --host-ids $HOSTS --output text
else
    echo "   none"
fi

echo "== security group"
SG_ID="$(aws ec2 describe-security-groups --filters "Name=group-name,Values=$NAME" \
    --query 'SecurityGroups[0].GroupId' --output text 2>/dev/null || true)"
if [ -n "$SG_ID" ] && [ "$SG_ID" != None ]; then
    # The interfaces of a terminated instance take a moment to let go of it.
    for _ in $(seq 1 12); do
        if aws ec2 delete-security-group --group-id "$SG_ID" 2>/dev/null; then
            echo "   deleted $SG_ID"
            break
        fi
        sleep 5
    done
else
    echo "   none"
fi

echo "== key pairs"
for key in "$NAME" "$NAME-rsa"; do
    aws ec2 delete-key-pair --key-name "$key" >/dev/null 2>&1 && echo "   deleted $key" || echo "   none ($key)"
done

rm -f "$STATE"/{hub_id,win_id,mac_id,mac_host_id,hub_ip,win_ip,mac_ip,hub_private_ip,win_private_ip,mac_private_ip,sg_id,enroll_link}
echo
"$HERE/status.sh"
