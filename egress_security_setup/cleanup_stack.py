import boto3
import time
import sys
from botocore.exceptions import ClientError

# ---------------------------
# AWS CLIENT
# ---------------------------
cf = boto3.client('cloudformation')

# ---------------------------
# STACKS TO DELETE (in reverse order)
# ---------------------------
STACKS = [
    "egressNGWStack",
    "gwlbeRouteStack",
    "gwlbeVPCStack",
    "egressVPCStack"
]

# ---------------------------
# HELPER FUNCTIONS
# ---------------------------
def delete_stack(stack_name):
    print(f"\n[START] Deleting stack: {stack_name}")
    try:
        cf.describe_stacks(StackName=stack_name)
    except ClientError as e:
        if "does not exist" in str(e):
            print(f"[SKIP] Stack {stack_name} does not exist.")
            return
        else:
            print(f"[ERROR] Describe failed: {e}")
            raise

    try:
        cf.delete_stack(StackName=stack_name)
        print(f"[DELETE] Delete request sent for stack: {stack_name}")
        wait_for_stack_deletion(stack_name)
    except ClientError as e:
        print(f"[ERROR] Failed to delete {stack_name}: {e}")
        raise

def wait_for_stack_deletion(stack_name):
    timeout, interval, elapsed = 900, 10, 0
    while elapsed < timeout:
        time.sleep(interval)
        elapsed += interval
        try:
            cf.describe_stacks(StackName=stack_name)
            print(f"  → {stack_name} still deleting...")
        except ClientError as e:
            if "does not exist" in str(e):
                print(f"[COMPLETE] Stack {stack_name} deleted.")
                return
            else:
                print(f"[ERROR] Failed to get deletion status: {e}")
                raise
    raise TimeoutError(f"Timeout waiting for stack {stack_name} deletion.")

# ---------------------------
# MAIN EXECUTION
# ---------------------------
if __name__ == '__main__':
    for stack_name in STACKS:
        try:
            delete_stack(stack_name)
        except Exception as e:
            print(f"[FAILED] Error deleting {stack_name}: {e}")
            sys.exit(1)
