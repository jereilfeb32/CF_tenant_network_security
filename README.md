🛡️ Customer Network Security Deployment

This repository automates the deployment of a centralized network security architecture on AWS using CloudFormation and Python. The design enables centralized inspection of traffic from multiple VPCs (spoke/egress) via a shared Gateway Load Balancer (GWLB) in a perimeter VPC.

## 📚 Overview

The solution consists of two main deployment units:

- **Perimeter Security Stack**:  
  Deploys a centralized Gateway Load Balancer (GWLB), associated EC2-based inspection appliances (e.g., FortiGate), and a GWLB **Endpoint Service** to allow other VPCs to route traffic for inspection.

- **Egress Security Stack**:  
  Deploys a customer/spoke VPC that connects to the centralized GWLB using **GWLB Endpoints (GWLBe)**. The egress VPC routes internet-bound traffic through these endpoints for centralized inspection.

## 📁 Directory Structure

├── perimeter\_security\_setup/         # Centralized inspection and GWLB service stack
│   ├── templates/                    # Templates for VPC, GWLB, EC2, Security Groups
│   ├── parameters/                   # JSON parameter files for CloudFormation
│   └── deployment.py                 # Deployment script for perimeter stack
│
├── egress\_security\_setup/           # Spoke/Egress VPC and GWLBe stack
│   ├── templates/                    # Templates for VPC, NAT Gateway, GWLBe
│   ├── parameters/                   # JSON parameter files for egress stack
│   └── deployment.py                 # Deployment script for egress stack
│
└── README.md                        # This documentation

## 🛠️ Prerequisites

Before running the deployment:

- ✅ AWS CLI configured and authenticated
- ✅ Python 3.7 or later
- ✅ Install required Python packages:
 
  pip install boto3

* ✅ IAM user/role must have the following permissions:

  * `cloudformation:*`
  * `ec2:*`
  * `iam:PassRole`
  * `ssm:*` *(optional, if storing private keys or parameters)*

## 🚀 Deployment Workflow

### ✅ Step 1: Deploy the Perimeter Stack (GWLB Service Provider)

This stack sets up:

* Central VPC
* Gateway Load Balancer (GWLB)
* Auto Scaling EC2 inspection appliances (e.g., FortiGate)
* GWLB Endpoint Service

cd perimeter_security_setup
python deployment.py


📤 **Output**: This will produce the `ServiceName` (e.g.,
`com.amazonaws.vpce.ap-southeast-1.vpce-svc-xxxxxxxxxxxxxxxxx`)
Use this ARN in the next step to register the egress VPC endpoints.

### 🔧 Step 2: Configure the Egress Stack (GWLB Consumer / Spoke VPC)

Before running the egress deployment script, update the `ServiceName` in the deployment definition with the value output from **Step 1**.

Example stack configuration:

{
    "name": "SEgwlbeStack",
    "template": "gwlb-endpoint.yaml",
    "parameters": [
        { "ParameterKey": "ProjectName", "ParameterValue": "customer-egress" },
        { "ParameterKey": "ServiceName", "ParameterValue": "com.amazonaws.vpce.ap-southeast-1.vpce-svc-0eaa5d68deb2856ba" }
    ],
    "parameters_from_outputs": [
        { "output_key": "VpcId", "parameter_key": "VpcId" },
        {
            "output_keys": ["GWLBSubnet1Id", "GWLBSubnet2Id", "GWLBSubnet3Id"],
            "parameter_key": "SubnetIds"
        }
    ],
    "outputs": ["GWLBEId1", "GWLBEId2", "GWLBEId3"]
}

> 📝 You may edit this configuration inside `deployment.py` or inject the `ServiceName` dynamically via parameter chaining.

### 🚀 Step 3: Deploy the Egress Stack

Once the configuration is set, run the deployment script for the egress VPC:

cd ../egress_security_setup
python deployment.py


This will:

* Deploy the spoke/egress VPC
* Create NAT Gateway and subnets
* Register GWLBe (GWLB Endpoints) to the centralized service

## 🔒 Security Considerations

* Ensure IAM roles used in automation follow the principle of least privilege.
* Use Systems Manager Parameter Store or AWS Secrets Manager to securely store sensitive information such as EC2 key pairs or license tokens.
* Consider enabling flow logs and inspection logs for auditing purposes.
