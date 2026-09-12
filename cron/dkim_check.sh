#!/bin/sh
# Simple script that triggers the daily check
curl -s -X POST http://localhost:8001/dkim/check > /dev/null
