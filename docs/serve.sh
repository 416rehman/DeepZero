#!/bin/bash
echo "Starting Jekyll server via Docker on http://localhost:4005..."

# Get the directory of this script, which is the docs/ folder
DOCS_DIR="$( cd "$( dirname "${BASH_SOURCE[0]}" )" &> /dev/null && pwd )"

# Use sudo to avoid docker.sock permission errors
# We pass JEKYLL_UID and JEKYLL_GID to ensure generated files aren't owned by root
sudo docker run --rm \
  --volume="$DOCS_DIR:/srv/jekyll" \
  -p 4005:4000 \
  -e JEKYLL_UID=$(id -u) \
  -e JEKYLL_GID=$(id -g) \
  jekyll/jekyll:4.2.0 \
  jekyll serve
