import csv
import hashlib
import hmac
import io
import json


def export_rows(rows, anonymize=False, salt=""):
    if anonymize and not salt:
        raise ValueError("Explicit nonempty salt required")
    stream = io.StringIO(newline="")
    writer = csv.DictWriter(stream, fieldnames=["tenant_id", "customer_id", "email"])
    writer.writeheader()
    for row in rows:
        if "customer_id" in row and "account_id" in row:
            if row["customer_id"] != row["account_id"]:
                raise ValueError("Conflicting identifiers")
        customer = row["customer_id"] if "customer_id" in row else row["account_id"]
        email = row["email"]
        if anonymize:
            payload = json.dumps([row["tenant_id"], customer]).encode()
            customer = hmac.new(salt.encode(), payload, hashlib.sha256).hexdigest()
            email = ""
        writer.writerow({"tenant_id": row["tenant_id"], "customer_id": customer, "email": email})
    return stream.getvalue()
