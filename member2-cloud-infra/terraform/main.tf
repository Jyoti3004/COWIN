############################################################
# CoWIN Vaccine Center Lookup - multi-AZ deployment on AWS
# 2 EC2 instances (ap-south-1a, ap-south-1b) behind an ALB
# Usage:  terraform init && terraform apply
# Destroy when done (saves cost):  terraform destroy
############################################################
terraform {
  required_providers {
    aws = { source = "hashicorp/aws", version = "~> 5.0" }
  }
}

provider "aws" {
  region = "ap-south-1" # Mumbai
}

variable "instance_type" {
  default = "t3.micro"
}

data "aws_vpc" "default" {
  default = true
}

data "aws_subnet" "az_a" {
  vpc_id            = data.aws_vpc.default.id
  availability_zone = "ap-south-1a"
  default_for_az    = true
}

data "aws_subnet" "az_b" {
  vpc_id            = data.aws_vpc.default.id
  availability_zone = "ap-south-1b"
  default_for_az    = true
}

data "aws_ami" "al2023" {
  most_recent = true
  owners      = ["amazon"]
  filter {
    name   = "name"
    values = ["al2023-ami-2023.*-x86_64"]
  }
}

resource "aws_security_group" "alb_sg" {
  name_prefix = "cowin-alb-"
  ingress {
    from_port   = 80
    to_port     = 80
    protocol    = "tcp"
    cidr_blocks = ["0.0.0.0/0"]
  }
  egress {
    from_port   = 0
    to_port     = 0
    protocol    = "-1"
    cidr_blocks = ["0.0.0.0/0"]
  }
}

resource "aws_security_group" "app_sg" {
  name_prefix = "cowin-app-"
  ingress {
    from_port       = 8080
    to_port         = 8080
    protocol        = "tcp"
    security_groups = [aws_security_group.alb_sg.id] # only the ALB may reach the app
  }
  egress {
    from_port   = 0
    to_port     = 0
    protocol    = "-1"
    cidr_blocks = ["0.0.0.0/0"]
  }
}

locals {
  # Writes app.py on the instance and runs it as a systemd service.
  user_data = { for z in ["ap-south-1a", "ap-south-1b"] : z => <<-EOT
    #!/bin/bash
    mkdir -p /srv/cowin
    cat > /srv/cowin/app.py <<'PYEOF'
    ${file("${path.module}/../../member1-app-and-architecture/app/app.py")}
    PYEOF
    cat > /etc/systemd/system/cowin.service <<UNIT
    [Unit]
    Description=CoWIN center lookup
    After=network.target
    [Service]
    Environment=ZONE=${z}
    Environment=PORT=8080
    ExecStart=/usr/bin/python3 /srv/cowin/app.py
    Restart=always
    [Install]
    WantedBy=multi-user.target
    UNIT
    systemctl daemon-reload
    systemctl enable --now cowin
    EOT
  }
}

resource "aws_instance" "zone_a" {
  ami                    = data.aws_ami.al2023.id
  instance_type          = var.instance_type
  subnet_id              = data.aws_subnet.az_a.id
  vpc_security_group_ids = [aws_security_group.app_sg.id]
  user_data              = local.user_data["ap-south-1a"]
  tags                   = { Name = "cowin-zone-a" }
}

resource "aws_instance" "zone_b" {
  ami                    = data.aws_ami.al2023.id
  instance_type          = var.instance_type
  subnet_id              = data.aws_subnet.az_b.id
  vpc_security_group_ids = [aws_security_group.app_sg.id]
  user_data              = local.user_data["ap-south-1b"]
  tags                   = { Name = "cowin-zone-b" }
}

resource "aws_lb" "alb" {
  name               = "cowin-alb"
  load_balancer_type = "application"
  security_groups    = [aws_security_group.alb_sg.id]
  subnets            = [data.aws_subnet.az_a.id, data.aws_subnet.az_b.id]
}

resource "aws_lb_target_group" "tg" {
  name     = "cowin-tg"
  port     = 8080
  protocol = "HTTP"
  vpc_id   = data.aws_vpc.default.id
  health_check {
    path                = "/health"
    interval            = 10
    timeout             = 5
    healthy_threshold   = 2
    unhealthy_threshold = 2
  }
}

resource "aws_lb_target_group_attachment" "a" {
  target_group_arn = aws_lb_target_group.tg.arn
  target_id        = aws_instance.zone_a.id
  port             = 8080
}

resource "aws_lb_target_group_attachment" "b" {
  target_group_arn = aws_lb_target_group.tg.arn
  target_id        = aws_instance.zone_b.id
  port             = 8080
}

resource "aws_lb_listener" "http" {
  load_balancer_arn = aws_lb.alb.arn
  port              = 80
  protocol          = "HTTP"
  default_action {
    type             = "forward"
    target_group_arn = aws_lb_target_group.tg.arn
  }
}

output "alb_url" {
  value = "http://${aws_lb.alb.dns_name}/health"
}
output "zone_a_instance_id" {
  value = aws_instance.zone_a.id
}
output "zone_b_instance_id" {
  value = aws_instance.zone_b.id
}
