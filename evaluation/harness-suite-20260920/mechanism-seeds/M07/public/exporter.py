import csv
import io


def export_rows(rows, anonymize=False, salt=""):
    if anonymize:
        raise NotImplementedError("Dashboard export has not been implemented")
    stream = io.StringIO(newline="")
    writer = csv.DictWriter(stream, fieldnames=["tenant_id", "customer_id", "email"])
    writer.writeheader()
    for row in rows:
        writer.writerow(row)
    return stream.getvalue()
