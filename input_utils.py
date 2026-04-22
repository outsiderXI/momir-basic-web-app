import sys
import termios
import tty


def esc_input(prompt="> "):
    sys.stdout.write(prompt)
    sys.stdout.flush()

    buf = ""

    fd = sys.stdin.fileno()
    old = termios.tcgetattr(fd)

    try:
        tty.setraw(fd)

        while True:
            ch = sys.stdin.read(1)

            if ch == "\x1b":
                sys.stdout.write("\n")
                sys.stdout.flush()
                return None

            elif ch in ("\r", "\n"):
                sys.stdout.write("\n")
                sys.stdout.flush()
                return buf

            elif ch == "\x7f":
                if buf:
                    buf = buf[:-1]
                    sys.stdout.write("\b \b")
                    sys.stdout.flush()

            else:
                buf += ch
                sys.stdout.write(ch)
                sys.stdout.flush()

    finally:
        termios.tcsetattr(fd, termios.TCSADRAIN, old)
