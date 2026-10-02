from exporter import export_rows


def render(rows, salt):
    return export_rows(rows, anonymize=True, salt=salt)
