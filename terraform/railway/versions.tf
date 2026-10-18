terraform {
  required_version = ">= 1.6"

  required_providers {
    railway = {
      source  = "terraform-community-providers/railway"
      version = "~> 0.6"
    }
    random = {
      source  = "hashicorp/random"
      version = "~> 3.6"
    }
  }

  # Local state by default. State holds the generated secrets (database password, keys), so
  # keep it out of git (see .gitignore here).
}

# Authenticates with the RAILWAY_TOKEN environment variable (an account or workspace token
# from https://railway.com/account/tokens). Do not put the token in a .tfvars file.
provider "railway" {}
