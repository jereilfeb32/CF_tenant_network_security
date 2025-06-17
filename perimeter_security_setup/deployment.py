import boto3
import sys
import os
import logging
import subprocess
import argparse
from botocore.exceptions import ClientError

# --- Logging setup ---
logging.basicConfig(level=logging.INFO, format='[%(asctime)s] %(levelname)s: %(message)s')
logger = logging.getLogger(__name__)

# --- AWS clients ---
cf = boto3.client('cloudformation')
ec2 = boto3.client('ec2')
sts = boto3.client('sts')

# --- Constants ---
TEMPLATE_DIR = "templates"

# --- Argument parsing ---
parser = argparse.ArgumentParser()
parser.add_argument('--force', action='store_true', help='Force update stacks even if already completed.')
args = parser.parse_args()

# --- VPC Stack deployment definition ---
vpc_stack_definition = {
    "name": "SecurityVPCStack",
    "template": "vpc.yaml",
    "parameters": [
        {"ParameterKey": "ProjectName", "ParameterValue": "SecurityPerimeter"},
        {"ParameterKey": "Owner", "ParameterValue": "Avaloq"},
        {"ParameterKey": "BusinessUnit", "ParameterValue": "RnD_department"},
        {"ParameterKey": "VpcCidr", "ParameterValue": "10.200.0.0/16"},
        {"ParameterKey": "Region", "ParameterValue": "ap-southeast-1"},
        {"ParameterKey": "AvailabilityZones", "ParameterValue": "ap-southeast-1a,ap-southeast-1b,ap-southeast-1c"},
        {"ParameterKey": "PublicSubnetCidrs", "ParameterValue": "10.200.1.0/24,10.200.2.0/24,10.200.3.0/24"},
        {"ParameterKey": "SecuritySubnetCidrs", "ParameterValue": "10.200.4.0/24,10.200.5.0/24,10.200.6.0/24"},
        {"ParameterKey": "GWLBSubnetCidrs", "ParameterValue": "10.200.7.0/24,10.200.8.0/24,10.200.9.0/24"},
        {"ParameterKey": "GWLBeSubnetCidrs", "ParameterValue": "10.200.10.0/24,10.200.11.0/24,10.200.12.0/24"},
        {"ParameterKey": "TGWSubnetCidrs", "ParameterValue": "10.200.13.0/24,10.200.14.0/24,10.200.15.0/24"}
    ],
    "outputs": [
        "VpcId",
        "PublicSubnet1Id", "PublicSubnet2Id", "PublicSubnet3Id",
        "SecuritySubnet1Id", "SecuritySubnet2Id", "SecuritySubnet3Id",
        "GWLBSubnet1Id", "GWLBSubnet2Id", "GWLBSubnet3Id",
        "GWLBeSubnet1Id", "GWLBeSubnet2Id", "GWLBeSubnet3Id",
        "TGWSubnet1Id", "TGWSubnet2Id", "TGWSubnet3Id"
    ]
}

# --- Security Group Stack deployment definition ---
security_group_stack_definition = {
    "name": "FortiGateSecurityGroupStack",
    "template": "ngfw-security-group.yaml",
    "parameters": [
        {"ParameterKey": "ProjectName", "ParameterValue": "SecurityPerimeter"},
        {"ParameterKey": "VpcId", "ParameterValue": ""}  # VPC ID will be set later
    ],
    "outputs": [
        "SecurityGroupId"
    ]
}

# --- GWLB Stack deployment definition ---
gwlb_stack_definition = {
    "name": "GWLBStack",
    "template": "gwlb.yaml",  # New template file for the GWLB
    "parameters": [
        {"ParameterKey": "ProjectName", "ParameterValue": "SecurityPerimeter"},
        {"ParameterKey": "VpcId", "ParameterValue": ""},  # VPC ID will be set later
        {"ParameterKey": "GWLBSubnetIds", "ParameterValue": ""}  # Subnet IDs will be set later
    ],
    "outputs": [
        "GWLBArn",
        "GWLBTargetGroupArn",
        "GWLBServiceName"
    ]
}

# --- GWLBe Stack deployment definition ---
gwlb_endpoint_stack_definition = {
    "name": "GWLBeStack",
    "template": "gwlb-endpoint.yaml",  # New template file for the GWLBe
    "parameters": [
        {"ParameterKey": "ProjectName", "ParameterValue": "SecurityPerimeter"},
        {"ParameterKey": "VpcId", "ParameterValue": ""},  # VPC ID will be set later
        {"ParameterKey": "GWLBEndpointSubnetIds", "ParameterValue": ""}  # Subnet IDs will be set later
    ],
    "outputs": [
        "GWLBEndpoint1Id",
        "GWLBEndpoint2Id",
        "GWLBEndpoint3Id"
    ]
}

# --- Auto Scaling Group Stack deployment definition ---
asg_stack_definition = {
    "name": "AutoScalingGroupStack",
    "template": "ec2-appliance.yaml",  # New template file for the Auto Scaling Group
    "parameters": [
        {"ParameterKey": "ProjectName", "ParameterValue": "SecurityPerimeter"},
        {"ParameterKey": "SecuritySubnetIds", "ParameterValue": ""},  # Security Subnet IDs will be set later
        {"ParameterKey": "GWLBSubnetIds", "ParameterValue": ""},  # GWLB Subnet IDs will be set later
        {"ParameterKey": "SecurityGroupId", "ParameterValue": ""},  # Security Group ID will be set later
        {"ParameterKey": "AmiId", "ParameterValue": "ami-0435fcf800fb5418d"},  # Static AMI ID
        {"ParameterKey": "GWLBTargetGroupArn", "ParameterValue": ""},  # GWLB Target Group ARN will be set later
        {"ParameterKey": "KeyPairName", "ParameterValue": "ngfw-key-pair"},  # Static Key Pair Name
        {"ParameterKey": "InstanceType", "ParameterValue": "t3.micro"},  # Default instance type
        {"ParameterKey": "NumberOfAZs", "ParameterValue": "3"}  # Default number of AZs
    ],
    "outputs": [
        "AutoScalingGroupName",
        "LaunchTemplateId",
        "KeyPairUsed"
    ]
}

def wait_for_completion(stack_name, operation):
    waiter_name = 'stack_create_complete' if operation == 'create_stack' else 'stack_update_complete'
    waiter = cf.get_waiter(waiter_name)
    logger.info(f"Waiting for {stack_name} to {operation.replace('_', ' ')}...")
    try:
        waiter.wait(StackName=stack_name)
        logger.info(f"{stack_name} {operation.replace('_', ' ')} completed successfully.")
    except Exception as e:
        logger.error(f"Error during stack wait: {e}")

def get_stack_status(stack_name):
    try:
        response = cf.describe_stacks(StackName=stack_name)
        return response['Stacks'][0]['StackStatus']
    except ClientError as e:
        if 'does not exist' in str(e):
            return None
        logger.error(f"Failed to get status of stack {stack_name}: {e}")
        return None

def deploy_stack(stack_def):
    stack_name = stack_def["name"]
    template_path = os.path.join(TEMPLATE_DIR, stack_def["template"])

    if not os.path.isfile(template_path):
        logger.error(f"Template file not found: {template_path}")
        return False

    with open(template_path, 'r') as f:
        template_body = f.read()

    try:
        cf.validate_template(TemplateBody=template_body)
    except ClientError as e:
        logger.error(f"Template validation failed: {e}")
        return False

    parameters = stack_def.get("parameters", [])

    # If deploying the security group stack, set the VPC ID parameter
    if stack_name == "FortiGateSecurityGroupStack":
        vpc_id = collected_outputs.get("VpcId")
        if vpc_id:
            parameters[1]["ParameterValue"] = vpc_id  # Set VPC ID

    # If deploying the GWLB stack, set the VPC ID and GWLB Subnet IDs parameters
    if stack_name == "GWLBStack":
        vpc_id = collected_outputs.get("VpcId")
        gwlb_subnet_ids = collected_outputs.get("GWLBSubnetIds")
        if vpc_id:
            parameters[1]["ParameterValue"] = vpc_id  # Set VPC ID
        if gwlb_subnet_ids:
            parameters[2]["ParameterValue"] = gwlb_subnet_ids  # Set GWLB Subnet IDs

    # If deploying the GWLBe stack, set the VPC ID and GWLBe Subnet IDs parameters
    if stack_name == "GWLBeStack":
        vpc_id = collected_outputs.get("VpcId")
        gwlb_endpoint_subnet_ids = collected_outputs.get("GWLBeSubnetIds")
        if vpc_id:
            parameters[1]["ParameterValue"] = vpc_id  # Set VPC ID
        if gwlb_endpoint_subnet_ids:
            parameters[2]["ParameterValue"] = gwlb_endpoint_subnet_ids  # Set GWLBe Subnet IDs

    # If deploying the ASG stack, set the necessary parameters
    if stack_name == "AutoScalingGroupStack":
        security_subnet_ids = collected_outputs.get("SecuritySubnetIds")
        gwlb_subnet_ids = collected_outputs.get("GWLBSubnetIds")
        security_group_id = collected_outputs.get("SecurityGroupId")
        gwlb_target_group_arn = collected_outputs.get("GWLBTargetGroupArn")

        if security_subnet_ids:
            parameters[1]["ParameterValue"] = security_subnet_ids  # Set Security Subnet IDs
        if gwlb_subnet_ids:
            parameters[2]["ParameterValue"] = gwlb_subnet_ids  # Set GWLB Subnet IDs
        if security_group_id:
            parameters[3]["ParameterValue"] = security_group_id  # Set Security Group ID
        if gwlb_target_group_arn:
            parameters[5]["ParameterValue"] = gwlb_target_group_arn  # Set GWLB Target Group ARN

    stack_status = get_stack_status(stack_name)
    try:
        if not stack_status:
            response = cf.create_stack(
                StackName=stack_name,
                TemplateBody=template_body,
                Parameters=parameters,
                Capabilities=['CAPABILITY_NAMED_IAM'],
                DisableRollback=True
            )
            logger.info(f"Creating stack: {response['StackId']}")
            wait_for_completion(stack_name, 'create_stack')
        elif stack_status in ["CREATE_COMPLETE", "UPDATE_COMPLETE"]:
            if not args.force:
                logger.info(f"Stack {stack_name} already exists. Skipping (use --force to override).")
                return True
            cf.update_stack(
                StackName=stack_name,
                TemplateBody=template_body,
                Parameters=parameters,
                Capabilities=['CAPABILITY_NAMED_IAM']
            )
            logger.info(f"Updating stack {stack_name}")
            wait_for_completion(stack_name, 'update_stack')
        else:
            logger.error(f"Stack {stack_name} is in unexpected state: {stack_status}")
            return False
        return True
    except ClientError as e:
        if "No updates are to be performed" in str(e):
            logger.info(f"No updates needed for stack {stack_name}.")
            return True
        logger.error(f"Error deploying stack {stack_name}: {e}")
        return False

def get_stack_outputs(stack_name):
    try:
        response = cf.describe_stacks(StackName=stack_name)
        return {o['OutputKey']: o['OutputValue'] for o in response['Stacks'][0].get('Outputs', [])}
    except ClientError as e:
        logger.error(f"Failed to get outputs for {stack_name}: {e}")
        return {}

def set_vpc_dns_attributes(vpc_id):
    try:
        ec2.modify_vpc_attribute(VpcId=vpc_id, EnableDnsSupport={'Value': True})
        ec2.modify_vpc_attribute(VpcId=vpc_id, EnableDnsHostnames={'Value': True})
        logger.info(f"Enabled DNS support and hostnames for VPC {vpc_id}")
    except ClientError as e:
        logger.error(f"Failed to modify VPC DNS attributes: {e}")
        sys.exit(1)

def join_subnet_ids(outputs, prefix, count=3):
    """Helper to join subnet IDs for a given prefix e.g. 'PublicSubnet1Id'..'PublicSubnet3Id'"""
    keys = [f"{prefix}{i}Id" for i in range(1, count+1)]
    missing = [k for k in keys if k not in outputs]
    if missing:
        logger.warning(f"Missing subnet IDs for joining: {', '.join(missing)}")
        return None
    return ",".join(outputs[k] for k in keys)

def add_vpc_endpoint_service_permission(region, target_account):
    ec2 = boto3.client('ec2', region_name=region)
    account_id = sts.get_caller_identity()['Account']

    logger.info(f"[INFO] Scanning for VPC Endpoint Services in region: {region} (Account: {account_id})")

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
        logger.error(f"[ERROR] Failed to fetch services: {e}")
        sys.exit(1)

    if not owned_service:
        logger.error("[ERROR] No VPC endpoint services owned by this account.")
        sys.exit(1)

    service_id = owned_service['ServiceId']
    service_name = owned_service['ServiceName']

    logger.info(f"[INFO] Found service: {service_name}")
    logger.info(f"[INFO] Adding permission for account {target_account}...")

    principal_arn = f"arn:aws:iam::{target_account}:root"

    try:
        ec2.modify_vpc_endpoint_service_permissions(
            ServiceId=service_id,
            AddAllowedPrincipals=[principal_arn]
        )
        logger.info(f"[SUCCESS] Permission added for account {target_account} to access service.")
        return service_id, service_name  # Return the service ID and name
    except Exception as e:
        logger.error(f"[ERROR] Failed to add permission: {e}")
        sys.exit(1)

if __name__ == "__main__":
    collected_outputs = {}

    # Deploy the VPC stack
    success = deploy_stack(vpc_stack_definition)
    if not success:
        logger.error("Aborting due to failed VPC stack deployment.")
        sys.exit(1)

    # Collect outputs from the VPC stack
    outputs = get_stack_outputs(vpc_stack_definition["name"])
    for key in vpc_stack_definition.get("outputs", []):
        if key in outputs:
            collected_outputs[key] = outputs[key]
        else:
            logger.warning(f"Output '{key}' not found in {vpc_stack_definition['name']}")

    # Join subnet IDs into comma-separated strings for easy reference
    subnet_groups = {
        "PublicSubnetIds": "PublicSubnet",
        "SecuritySubnetIds": "SecuritySubnet",
        "GWLBSubnetIds": "GWLBSubnet",
        "GWLBeSubnetIds": "GWLBeSubnet",
        "TGWSubnetIds": "TGWSubnet"
    }

    for joined_key, prefix in subnet_groups.items():
        joined_value = join_subnet_ids(collected_outputs, prefix)
        if joined_value:
            collected_outputs[joined_key] = joined_value
            logger.info(f"Joined {joined_key}: {joined_value}")
        else:
            logger.warning(f"Could not join subnet IDs for {joined_key}")

    # Deploy the Security Group stack
    success = deploy_stack(security_group_stack_definition)
    if not success:
        logger.error("Aborting due to failed Security Group stack deployment.")
        sys.exit(1)

    # Collect outputs from the Security Group stack
    outputs = get_stack_outputs(security_group_stack_definition["name"])
    for key in security_group_stack_definition.get("outputs", []):
        if key in outputs:
            collected_outputs[key] = outputs[key]
        else:
            logger.warning(f"Output '{key}' not found in {security_group_stack_definition['name']}")

    # Deploy the GWLB stack
    success = deploy_stack(gwlb_stack_definition)
    if not success:
        logger.error("Aborting due to failed GWLB stack deployment.")
        sys.exit(1)

    # Collect outputs from the GWLB stack
    outputs = get_stack_outputs(gwlb_stack_definition["name"])
    for key in gwlb_stack_definition.get("outputs", []):
        if key in outputs:
            collected_outputs[key] = outputs[key]
        else:
            logger.warning(f"Output '{key}' not found in {gwlb_stack_definition['name']}")

# Deploy the GWLBe stack
success = deploy_stack(gwlb_endpoint_stack_definition)
if not success:
    logger.error("Aborting due to failed GWLBe stack deployment.")
    sys.exit(1)

# Collect outputs from the GWLBe stack
outputs = get_stack_outputs(gwlb_endpoint_stack_definition["name"])
for key in gwlb_endpoint_stack_definition.get("outputs", []):
    if key in outputs:
        collected_outputs[key] = outputs[key]
    else:
        logger.warning(f"Output '{key}' not found in {gwlb_endpoint_stack_definition['name']}")

# Log details about the GWLBe endpoint and permissions
gwlbe_service_id = collected_outputs.get("GWLBeServiceId")  # Assuming you have this output
gwlbe_service_name = collected_outputs.get("GWLBeServiceName")  # Assuming you have this output
target_account_id = "975050199901"  # Replace with the actual target account ID

if gwlbe_service_id and gwlbe_service_name:
    logger.info("Preparing to add cross-account permissions for GWLBe endpoint:")
    logger.info("----------------------------------------------------------")
    logger.info(f"  Service ID:         {gwlbe_service_id}")
    logger.info(f"  Service Name:       {gwlbe_service_name}")
    logger.info(f"  Target Account ID:  {target_account_id}")
    logger.info("----------------------------------------------------------")

# Deploy the Auto Scaling Group stack
asg_stack_definition["parameters"][1]["ParameterValue"] = collected_outputs.get("SecuritySubnetIds", "")
asg_stack_definition["parameters"][2]["ParameterValue"] = collected_outputs.get("GWLBSubnetIds", "")
asg_stack_definition["parameters"][3]["ParameterValue"] = collected_outputs.get("SecurityGroupId", "")
asg_stack_definition["parameters"][5]["ParameterValue"] = collected_outputs.get("GWLBTargetGroupArn", "")
success = deploy_stack(asg_stack_definition)
if not success:
    logger.error("Aborting due to failed Auto Scaling Group stack deployment.")
    sys.exit(1)

# Enable DNS attributes for the VPC
set_vpc_dns_attributes(collected_outputs["VpcId"])
logger.info("\n--- Completed all CloudFormation stack deployments ---")

# --- Run external script to add VPC Endpoint Service Permission ---
try:
    result = subprocess.run(
        ["python", "Add-VPCEndpointServicePermission.py"],
        capture_output=True,
        text=True,
        check=True
    )
    logger.info("[Add-VPCEndpointServicePermission.py] Output:")
    logger.info("----------------------------------------------------------")
    logger.info(result.stdout)
    if result.stderr:
        logger.warning("[Add-VPCEndpointServicePermission.py] Errors:")
        logger.warning(result.stderr)
    logger.info("----------------------------------------------------------")
except subprocess.CalledProcessError as e:
    logger.error(f"Error running Add-VPCEndpointServicePermission.py: {e}")
    logger.error(f"Stdout: {e.stdout}")
    logger.error(f"Stderr: {e.stderr}")
    sys.exit(1)
