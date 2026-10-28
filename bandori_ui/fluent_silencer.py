import contextlib
import io


_ALERT_TEXT = "QFluentWidgets Pro is now released"


def import_qfluentwidgets(import_func):
    stdout = io.StringIO()
    with contextlib.redirect_stdout(stdout):
        result = import_func()
    output = stdout.getvalue()
    if output and _ALERT_TEXT not in output:
        print(output, end="")
    return result
