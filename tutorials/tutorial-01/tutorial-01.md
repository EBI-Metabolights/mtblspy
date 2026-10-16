# ELIXIR Metabolomics Community Meeting 2026 tutorial

This tutorial walks you through the complete workflow for submitting and an example metabolomics dataset to [MetaboLights test server](https://wwwdev.ebi.ac.uk/metabolights/) using the [mtblspy](https://github.com/EBI-Metabolights/mtblspy.git) utility tool.

In this tutorial, we will follow these steps:

1. Setting up your MetaboLights test account
2. Installing mtblspy library
3. ***UPDATE ME***

## 1. Setting up your MetaboLights test account

All programmatic interactions with MetaboLights — creating studies, uploading files, and triggering validation — require authentication. Follow the steps below to create your free account on MetaboLights test system.

- Set up the [MetaboLights Test Account](https://wwwdev.ebi.ac.uk/metabolights/editor)
- Confirm your account by clicking the link in the confirmation email
- Log in at [MetaboLights Test](https://wwwdev.ebi.ac.uk/metabolights/editor)

- Open a terminal and set the MetaboLights test server URL as an environment variable

```bash
export MTBLS_SERVER_URL=https://wwwdev.ebi.ac.uk/metabolights/ws
echo $MTBLS_SERVER_URL
```

## 2. Setting up mtblspy library

The `mtblspy` library is a command-line tool that helps dataset validation and submission tasks programmatically. To get started, you need two prerequisites: the [uv](https://docs.astral.sh/uv/) Python package manager (for dependency management) and [git](https://git-scm.com/) (to clone the repository).

- Install uv python package manager and git (if not already installed):

```bash
# install python package manager uv
curl -LsSf https://releases.astral.sh/github/uv/releases/download/0.13.1/uv-installer.sh | sh

# add $HOME/.local/bin to your PATH, either restart your shell or run
# export PATH=$HOME/.local/bin:$PATH

# install git (https://git-scm.com/install)
# Mac users may install git using Homebrew:
# brew install git

uv --version
# should print something like:
#uv 0.11.8 (0e961dd9a 2026-04-27 aarch64-apple-darwin)

git --version
# should print something like:
# git version 2.50.1 (Apple Git-155)

```

- Clone and install mtblspy locally:

```bash

# You may choose to work in a different directory for this tutorial.
# In that case, change the directory (or cd) command accordingly
# (Linux or Mac)
mkdir -p ~/tutorials/mtblspy-tutorials
cd ~/tutorials/mtblspy-tutorials

git clone https://github.com/EBI-Metabolights/mtblspy.git
cd mtblspy
uv python pin 3.14
uv sync
source .venv/bin/activate

# On Windows, you may need to run:
# .venv\Scripts\Activate.ps1

mtbls
# Usage: mtbls [OPTIONS] COMMAND [ARGS]...

#   MetaboLights Submission CLI.

#   A command line interface for creating, listing, and submitting studies to
#   MetaboLights.

# Options:
#   --version   Show the version and exit.
#   -h, --help  Show this message and exit.

# Commands:
#   auth        Authentication management.
#   config      Configuration management.
#   submission  Commands to use MetaboLights study submission REST API.
```

## 3. xxx
