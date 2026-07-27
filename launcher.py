"""Protected entry point for optional Chengsi compatibility patches."""

import clipboard_compat
import main


if __name__ == "__main__":
    clipboard_compat.install(main)
    main.main()
