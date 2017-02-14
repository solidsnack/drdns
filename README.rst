==============================
Dr. DNS -- Dynamic DNS for AWS
==============================

Dr. DNS is a serverless app providing dynamic DNS on AWS. EC2 instances tagged
with a `Name` that matches one of your domains in Route 53 will automatically
have entries created (and removed) for them on startup (and shutdown/stop).


.. image:: cfn.png
   :target: https://us-west-2.console.aws.amazon.com/cloudformation/designer/home?templateUrl=https://s3-us-west-2.amazonaws.com/s3.drcloud.io/drdns/drdns.template.json

`View in the CloudFormation template designer.`_

.. _View in the CloudFormation template designer.: https://us-west-2.console.aws.amazon.com/cloudformation/designer/home?templateUrl=https://s3-us-west-2.amazonaws.com/s3.drcloud.io/drdns/drdns.template.json
