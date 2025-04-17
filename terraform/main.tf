provider "google" {
  project = var.project_id
  region  = var.region
  zone    = var.zone
}

data "google_compute_network" "default" {
  name = "default"
}

resource "google_compute_firewall" "http-https" {
  name    = "ppl-allow-http-https"
  network = data.google_compute_network.default.name

  allow {
    protocol = "tcp"
    ports    = ["80", "443"]
  }

  source_ranges = ["0.0.0.0/0"]
}

resource "google_compute_firewall" "allow-postgres" {
  name    = "ppl-allow-postgres"
  network = data.google_compute_network.default.name

  allow {
    protocol = "tcp"
    ports    = ["5432"]
  }

  #source_ranges = ["2.80.118.223/32"]
  source_ranges = ["0.0.0.0/0"]
  description   = "Allow external access to PostgreSQL"
}

resource "google_compute_address" "static_ip" {
  name = "ppl-static-ip"
}

resource "google_compute_instance" "ppl" {
  name         = "ppl-instance"
  machine_type = "e2-micro"
  zone         = var.zone

  allow_stopping_for_update = true
  
  boot_disk {
    initialize_params {
      image = "debian-cloud/debian-11"
      size  = 10
    }
  }

  network_interface {
    network = data.google_compute_network.default.name
    access_config {
      nat_ip = google_compute_address.static_ip.address
    }
  }

  service_account {
    email  = google_service_account.vm_sa.email
    scopes = ["https://www.googleapis.com/auth/cloud-platform"]
  }

  metadata_startup_script = <<-EOF
    #!/bin/bash
    apt update
    apt install -y docker.io
    systemctl start docker
    docker run -d -p 80:80 your-dockerhub-user/porto-padel-league
  EOF

  tags = ["http-server", "https-server"]
}

resource "google_storage_bucket" "general" {
  name     = "portopadelleague-storage"
  location = "europe-west1"
  storage_class = "NEARLINE"

  force_destroy = true
  uniform_bucket_level_access = true
}

resource "google_service_account" "vm_sa" {
  account_id   = "ppl-vm-sa"
  display_name = "Porto Padel League VM SA"
}

resource "google_storage_bucket_iam_member" "allow_instance_uploads" {
  bucket = google_storage_bucket.general.name
  role   = "roles/storage.objectCreator"
  member = "serviceAccount:${google_service_account.vm_sa.email}"
}