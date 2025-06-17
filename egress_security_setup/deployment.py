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

# --- Constants ---
TEMPLATE_DIR = "templates"

# --- Argument parsing ---
parser = argparse.ArgumentParser()
parser.add_argument('--force', action='store_true', help='Force update stacks even if already completed.')
args = parser.parse_args()

# --- Stack deployment definitions ---
stack_definitions = [
    {
        "name": "SEvpcStack",
        "template": "vpc.yaml",
        "parameters": [
            {"ParameterKey": "ProjectName", "ParameterValue": "customer-egress"},
            {"ParameterKey": "VpcCidr", "ParameterValue": "10.100.0.0/16"},
            {"ParameterKey": "AvailabilityZones", "ParameterValue": "ap-southeast-1a,ap-southeast-1b,ap-southeast-1c"},
            {"ParameterKey": "PublicSubnetCidrs", "ParameterValue": "10.100.0.0/24,10.100.1.0/24,10.100.2.0/24"},
            {"ParameterKey": "PrivateSubnetCidrs", "ParameterValue": "10.100.10.0/24,10.100.11.0/24,10.100.12.0/24"},
            {"ParameterKey": "TGWSubnetCidrs", "ParameterValue": "10.100.20.0/24,10.100.21.0/24,10.100.22.0/24"},
            {"ParameterKey": "GWLBSubnetCidrs", "ParameterValue": "10.100.30.0/24,10.100.31.0/24,10.100.32.0/24"}
        ],
        "outputs": [
            "VpcId", "GWLBSubnet1Id", "GWLBSubnet2Id", "GWLBSubnet3Id", 
            "PublicSubnet1Id", "PublicSubnet2Id", "PublicSubnet3Id"  # Ensure these are included
        ]
    },
    {
        "name": "SEgwlbeStack",
        "template": "gwlb-endpoint.yaml",
        "parameters": [
            {"ParameterKey": "ProjectName", "ParameterValue": "customer-egress"},
            {"ParameterKey": "ServiceName", "ParameterValue": "com.amazonaws.vpce.ap-southeast-1.vpce-svc-0eaa5d68deb2856ba"}
        ],
        "parameters_from_outputs": [
            {"output_key": "VpcId", "parameter_key": "VpcId"},
            {
                "output_keys": ["GWLBSubnet1Id", "GWLBSubnet2Id", "GWLBSubnet3Id"],
                "parameter_key": "SubnetIds"
            }
        ],
        "outputs": ["GWLBEId1", "GWLBEId2", "GWLBEId3"]
    },
    {
        "name": "SEngwStack",
        "template": "ngw.yaml",
        "parameters": [
            {"ParameterKey": "ProjectName", "ParameterValue": "customer-egress"},
            {"ParameterKey": "VpcId", "ParameterValue": ""},  # To be filled from outputs
            {
                "ParameterKey": "PublicSubnetIds",
                "ParameterValue": ""  # To be filled from outputs
            }
        ],
        "parameters_from_outputs": [
            {"output_key": "VpcId", "parameter_key": "VpcId"},
            {
                "output_keys": ["PublicSubnet1Id", "PublicSubnet2Id", "PublicSubnet3Id"],
                "parameter_key": "PublicSubnetIds"
            }
        ],
        "outputs": ["NatGateway1Id", "NatGateway2Id", "NatGateway3Id", "NatEIP1Id", "NatEIP2Id", "NatEIP3Id"]
    }
]

def wait_for_completion(stack_name, operation):
    """Wait for a CloudFormation stack operation to complete."""
    waiter_name = 'stack_create_complete' if operation == 'create_stack' else 'stack_update_complete'
    waiter = cf.get_waiter(waiter_name)
    logger.info(f"Waiting for {stack_name} to {operation.replace('_', ' ')}...")
    try:
        waiter.wait(StackName=stack_name)
        logger.info(f"{stack_name} {operation.replace('_', ' ')} completed successfully.")
    except Exception as e:
        logger.error(f"Error during stack wait: {e}")
        sys.exit(1)  # Exit if waiting fails

def get_stack_status(stack_name):
    """Retrieve the current status of a CloudFormation stack."""
    try:
        response = cf.describe_stacks(StackName=stack_name)
        return response['Stacks'][0]['StackStatus']
    except ClientError as e:
        if 'does not exist' in str(e):
            return None
        logger.error(f"Failed to get status of stack {stack_name}: {e}")
        return None

def deploy_stack(stack_def, collected_outputs):
    """Deploy a CloudFormation stack based on the provided definition."""
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

    parameters = list(stack_def.get("parameters", []))

    for p in stack_def.get("parameters_from_outputs", []):
        if "output_key" in p:
            key = p["output_key"]
            if key not in collected_outputs:
                logger.error(f"Missing required output '{key}' for stack {stack_name}")
                return False
            parameters.append({
                "ParameterKey": p["parameter_key"],
                "ParameterValue": collected_outputs[key]
            })
        elif "output_keys" in p:
            values = [collected_outputs.get(k) for k in p["output_keys"]]
            if None in values:
                missing = [k for k in p["output_keys"] if collected_outputs.get(k) is None]
                logger.error(f"Missing required output(s) {', '.join(missing)} for stack {stack_name}")
                return False
            parameters.append({
                "ParameterKey": p["parameter_key"],
                "ParameterValue": ",".join(values)
            })
        else:
            logger.error(f"Invalid parameter mapping in stack {stack_name}: {p}")
            return False

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
    """Retrieve the outputs of a CloudFormation stack."""
    try:
        response = cf.describe_stacks(StackName=stack_name)
        return {o['OutputKey']: o['OutputValue'] for o in response['Stacks'][0].get('Outputs', [])}
    except ClientError as e:
        logger.error(f"Failed to get outputs for {stack_name}: {e}")
        return {}

def set_vpc_dns_attributes(vpc_id):
    """Enable DNS support and hostnames for the specified VPC."""
    try:
        ec2.modify_vpc_attribute(VpcId=vpc_id, EnableDnsSupport={'Value': True})
        ec2.modify_vpc_attribute(VpcId=vpc_id, EnableDnsHostnames={'Value': True})
        logger.info(f"Enabled DNS support and hostnames for VPC {vpc_id}")
    except ClientError as e:
        logger.error(f"Failed to modify VPC DNS attributes: {e}")
        sys.exit(1)

if __name__ == "__main__":
    collected_outputs = {}

    for stack in stack_definitions:
        success = deploy_stack(stack, collected_outputs)
        if not success:
            logger.error("Aborting pipeline due to failed stack.")
            sys.exit(1)

        outputs = get_stack_outputs(stack["name"])
        for key in stack.get("outputs", []):
            if key in outputs:
                collected_outputs[key] = outputs[key]
            else:
                logger.warning(f"Output '{key}' not found in {stack['name']}")

        # === DERIVED OUTPUTS after SEvpcStack ===
        if stack["name"] == "SEvpcStack":
            # Build GWLBSubnetIds
            gwlb_required = ["GWLBSubnet1Id", "GWLBSubnet2Id", "GWLBSubnet3Id"]
            if all(k in collected_outputs for k in gwlb_required):
                collected_outputs["GWLBSubnetIds"] = ",".join(collected_outputs[k] for k in gwlb_required)
            else:
                missing = [k for k in gwlb_required if k not in collected_outputs]
                logger.error(f"Missing GWLB subnet IDs: {', '.join(missing)}")
                sys.exit(1)

            # Collect Public Subnet IDs
            public_subnet_required = ["PublicSubnet1Id", "PublicSubnet2Id", "PublicSubnet3Id"]
            if all(k in collected_outputs for k in public_subnet_required):
                collected_outputs["PublicSubnetIds"] = ",".join(collected_outputs[k] for k in public_subnet_required)
            else:
                missing = [k for k in public_subnet_required if k not in collected_outputs]
                logger.error(f"Missing public subnet IDs: {', '.join(missing)}")
                sys.exit(1)

            # Enable DNS attributes
            set_vpc_dns_attributes(collected_outputs["VpcId"])

            logger.info("\n--- Derived Outputs after SEvpcStack ---")
            logger.info(f"GWLBSubnetIds: {collected_outputs['GWLBSubnetIds']}")
            logger.info(f"PublicSubnetIds: {collected_outputs['PublicSubnetIds']}")
