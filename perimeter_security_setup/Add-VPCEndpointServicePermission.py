import boto3
import sys

def add_vpc_endpoint_service_permission(region, target_account):
    ec2 = boto3.client('ec2', region_name=region)
    sts = boto3.client('sts')
    account_id = sts.get_caller_identity()['Account']

    print(f"[INFO] Scanning for VPC Endpoint Services in region: {region} (Account: {account_id})")

    paginator = ec2.get_paginator('describe_vpc_endpoint_services')
    owned_service = None

    try:
        for page in paginator.paginate():
            for service in page.get('ServiceDetails', []):
                if service.get('Owner') == account_id:
                    owned_service = service
                    break
            if owned_service:
                break
    except Exception as e:
        print(f"[ERROR] Failed to fetch services: {e}")
        sys.exit(1)

    if not owned_service:
        print("[ERROR] No VPC endpoint services owned by this account.")
        sys.exit(1)

    service_id = owned_service['ServiceId']
    service_name = owned_service['ServiceName']

    print(f"[INFO] Found service: {service_name}")
    print(f"[INFO] Adding permission for account {target_account}...")

    principal_arn = f"arn:aws:iam::{target_account}:root"

    try:
        ec2.modify_vpc_endpoint_service_permissions(
            ServiceId=service_id,
            AddAllowedPrincipals=[principal_arn]
        )
        print(f"[SUCCESS] Permission added for account {target_account} to access service.")
    except Exception as e:
        print(f"[ERROR] Failed to add permission: {e}")
        sys.exit(1)

if __name__ == "__main__":
    region = "ap-southeast-1"
    target_account = "975050199901"
    add_vpc_endpoint_service_permission(region, target_account)
