import boto3

# -------- Configuration --------
region = "ap-southeast-1"
spoke_vpc_id = None  # Set your spoke VPC ID, or leave None to check all VPCs

# -------- Initialize Boto3 Client --------
ec2 = boto3.client("ec2", region_name=region)

# -------- Retrieve GWLBe Endpoints --------
filters = [{"Name": "vpc-endpoint-type", "Values": ["GatewayLoadBalancer"]}]
if spoke_vpc_id:
    filters.append({"Name": "vpc-id", "Values": [spoke_vpc_id]})

print("Retrieving Gateway Load Balancer Endpoints...")
response = ec2.describe_vpc_endpoints(Filters=filters)
endpoints = response.get("VpcEndpoints", [])

if not endpoints:
    print("No GWLBe endpoints found.")
    exit(1)

# Fetch all service details
services_response = ec2.describe_vpc_endpoint_services()
service_details = services_response["ServiceDetails"]

for ep in endpoints:
    ep_id = ep["VpcEndpointId"]
    service_name = ep["ServiceName"]
    subnet_ids = ep["SubnetIds"]
    vpc_id = ep["VpcId"]

    print(f"\nGWLBe ID: {ep_id}")
    print(f"  VPC ID: {vpc_id}")
    print(f"  Subnets: {', '.join(subnet_ids)}")
    print(f"  Service Name: {service_name}")

    # Extract service ID from service name
    service_id = service_name.split(".")[-1]

    # Match service detail
    matched_service = next((s for s in service_details if s["ServiceId"] == service_id), None)

    if matched_service:
        print(f"  Service ID: {matched_service['ServiceId']}")
        print(f"  Service Owner: {matched_service['Owner']}")
        print(f"  Acceptance Required: {matched_service['AcceptanceRequired']}")
        print(f"  Service Type: {matched_service['ServiceType'][0]['ServiceType']}")
    else:
        print("  Warning: Service details not found. The service may not be shared with this account.")

print("\nValidation complete.")
