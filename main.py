#!/usr/bin/env python3
import logging

from commands import cli

logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")

if __name__ == "__main__":
    cli()
