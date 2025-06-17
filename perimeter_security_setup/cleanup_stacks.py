import boto3
import sys
import time
import logging
from botocore.exceptions import ClientError, BotoCoreError

# ---------------------------
# CONFIGURE LOGGING
# ---------------------------
logging.basicConfig(
    level=logging.INFO,
    format='[%(asctime)s] %(levelname)s: %(message)s',
    handlers=[
        logging.FileHandler("cleanup.log", encoding='utf-8'),
        logging.StreamHandler(sys.stdout)
    ]
)
logger = logging.getLogger(__name__)

# ---------------------------
# AWS CLIENT SETUP
# ---------------------------
try:
    cf = boto3.client('cloudformation')
except (BotoCoreError, ClientError) as e:
    logger.exception("Failed to create CloudFormation client.")
    sys.exit(1)

# ---------------------------
# STACKS TO DELETE (reverse order of deployment)
# ---------------------------
STACKS = [
    "perimetergwlbeStack",
    "perimeterec2Stack",
    "perimeterGWLBStack",
    "perimeterSGStack",
    "perimeterVPCstack"
]

# ---------------------------
# DELETE STACK FUNCTION
# ---------------------------
def delete_stack(stack_name):
    logger.info(f"[START] Deleting stack: {stack_name}")
    try:
        cf.describe_stacks(StackName=stack_name)
    except ClientError as e:
        if "does not exist" in str(e):
            logger.warning(f"[SKIP] Stack {stack_name} does not exist.")
            return
        else:
            logger.error(f"[ERROR] Describe failed for {stack_name}: {e}")
            raise

    try:
        cf.delete_stack(StackName=stack_name)
        logger.info(f"[DELETE] Delete request sent for stack: {stack_name}")
        wait_for_stack_deletion(stack_name)
    except ClientError as e:
        logger.error(f"[ERROR] Failed to delete {stack_name}: {e}")
        raise

def wait_for_stack_deletion(stack_name):
    timeout = 900  # seconds
    interval = 10
    elapsed = 0

    logger.info(f"Waiting for stack '{stack_name}' to be deleted...")

    while elapsed < timeout:
        time.sleep(interval)
        elapsed += interval
        try:
            cf.describe_stacks(StackName=stack_name)
            logger.info(f"  -> {stack_name} still deleting...")
        except ClientError as e:
            if "does not exist" in str(e):
                logger.info(f"[COMPLETE] Stack {stack_name} successfully deleted.")
                return
            else:
                logger.error(f"[ERROR] Checking deletion status failed: {e}")
                raise

    raise TimeoutError(f"Timeout waiting for stack {stack_name} deletion.")

# ---------------------------
# MAIN EXECUTION
# ---------------------------
if __name__ == "__main__":
    try:
        for stack_name in STACKS:
            delete_stack(stack_name)
    except Exception as e:
        logger.exception(f"[FAILED] Cleanup pipeline stopped: {e}")
        sys.exit(1)
