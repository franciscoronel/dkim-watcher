#!/bin/sh
# Simple script that triggers the daily check
curl -s -X POST http://localhost:8000/dkim/check > /dev/null
