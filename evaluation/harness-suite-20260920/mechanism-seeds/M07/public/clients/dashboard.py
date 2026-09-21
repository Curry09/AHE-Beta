from exporter import export_rows


def render(rows, salt):
    # This prototype currently exposes raw customer details.
    return export_rows(rows)
