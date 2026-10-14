import os
from datetime import datetime, timedelta, timezone

import boto3
from botocore.exceptions import ClientError

# 1. Initialize the EC2 client
ec2 = boto3.client("ec2")

VOLUME_ID = os.environ.get("VOLUME_ID", "vol-xxxxxxxxxxxxxxxxx")
DEFAULT_RETENTION_DAYS = int(os.environ.get("RETENTION_DAYS", "30"))


def lambda_handler(event, context):
    event = event or {}

    # Retention can be overridden from the test event (useful for demos).
    if "retention_minutes" in event:
        age = timedelta(minutes=int(event["retention_minutes"]))
    else:
        age = timedelta(days=int(event.get("retention_days", DEFAULT_RETENTION_DAYS)))

    cutoff = datetime.now(timezone.utc) - age
    print(f"Volume: {VOLUME_ID}")
    print(f"Deleting snapshots started before: {cutoff.isoformat()}")

    # 2. Create a snapshot of the specified volume
    response = ec2.create_snapshot(
        VolumeId=VOLUME_ID,
        Description=f"Automated backup of {VOLUME_ID}",
        TagSpecifications=[
            {
                "ResourceType": "snapshot",
                "Tags": [{"Key": "CreatedBy", "Value": "lambda-ebs-backup"}],
            }
        ],
    )
    created_id = response["SnapshotId"]
    print(f"Created snapshot: {created_id}")

    # 3. List this volume's own snapshots and delete the old ones
    deleted = []
    skipped = []
    paginator = ec2.get_paginator("describe_snapshots")
    pages = paginator.paginate(
        OwnerIds=["self"],
        Filters=[{"Name": "volume-id", "Values": [VOLUME_ID]}],
    )
    for page in pages:
        for snap in page["Snapshots"]:
            snap_id = snap["SnapshotId"]
            if snap_id == created_id:
                continue  # never delete the snapshot we just made
            if snap["StartTime"] < cutoff:
                try:
                    ec2.delete_snapshot(SnapshotId=snap_id)
                    deleted.append(snap_id)
                    # 4. Log the deleted snapshot ID
                    print(f"Deleted snapshot: {snap_id}")
                except ClientError as err:
                    code = err.response["Error"]["Code"]
                    print(f"Could not delete {snap_id}: {code}")
                    skipped.append(snap_id)

    print(f"Summary: created {created_id}, deleted {len(deleted)}, skipped {len(skipped)}")
    return {"created": created_id, "deleted": deleted, "skipped": skipped}
