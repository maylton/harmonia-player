import os

# Automated tests must never read or prompt for a developer's desktop keyring.
os.environ["HARMONIA_DISABLE_SECRET_SERVICE"] = "1"
