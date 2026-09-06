"""LLDB command that captures QQNT database-key candidates without printing them.

This file intentionally uses syntax supported by the older Python runtime bundled
with Xcode's LLDB. Import it from LLDB, not from the application process.
"""

from __future__ import print_function

import hashlib
import errno
import os
import shlex

import lldb


def _output_directory():
    value = os.environ.get("QQNT_KEY_DIR")
    if not value:
        raise RuntimeError("set QQNT_KEY_DIR before starting LLDB")
    path = os.path.abspath(os.path.expanduser(value))
    if not os.path.isdir(path):
        os.makedirs(path, 0o700)
    os.chmod(path, 0o700)
    return path


def capture_key(frame, _breakpoint_location, _extra_args, _internal_dict):
    """Breakpoint callback: x2 is the key pointer and x3 is its length."""
    pointer_register = frame.FindRegister("x2")
    length_register = frame.FindRegister("x3")
    if not pointer_register.IsValid() or not length_register.IsValid():
        print("[qqnt-key] unable to read x2/x3")
        return False

    pointer = pointer_register.GetValueAsUnsigned()
    length = length_register.GetValueAsUnsigned()
    if pointer == 0 or length < 8 or length > 128:
        return False

    error = lldb.SBError()
    raw = frame.GetThread().GetProcess().ReadMemory(pointer, length, error)
    if not error.Success() or raw is None or len(raw) != length:
        print("[qqnt-key] memory read failed")
        return False
    if isinstance(raw, str):
        raw = raw.encode("latin1")

    digest = hashlib.sha256(raw).hexdigest()
    destination = os.path.join(_output_directory(), digest + ".key")
    try:
        descriptor = os.open(
            destination,
            os.O_WRONLY | os.O_CREAT | os.O_EXCL,
            0o600,
        )
    except OSError as exc:
        if exc.errno != errno.EEXIST:
            print("[qqnt-key] cannot create private candidate file")
            return False
        descriptor = None
    if descriptor is not None:
        try:
            os.write(descriptor, raw)
        finally:
            os.close(descriptor)
    try:
        os.chmod(destination, 0o600)
    except OSError:
        print("[qqnt-key] cannot secure candidate-file permissions")
        return False
    print(
        "[qqnt-key] candidate saved privately: fingerprint=%s bytes=%d"
        % (digest[:12], length)
    )
    return False


def install(debugger, command, result, _internal_dict):
    """Install a module-relative key breakpoint: qqnt-install <hex-va>."""
    try:
        arguments = shlex.split(command)
        if len(arguments) not in (1, 2):
            raise ValueError("usage: qqnt-install <hex-va> [module-name]")
        address = int(arguments[0], 0)
        module = arguments[1] if len(arguments) == 2 else "wrapper.node"
        target = debugger.GetSelectedTarget()
        before = target.GetNumBreakpoints()
        debugger.HandleCommand(
            "breakpoint set --shlib %s --address 0x%x" % (module, address)
        )
        if target.GetNumBreakpoints() != before + 1:
            raise RuntimeError(
                "breakpoint was not created; run QQ once, interrupt it, then retry"
            )
        breakpoint = target.GetBreakpointAtIndex(target.GetNumBreakpoints() - 1)
        breakpoint.SetScriptCallbackFunction(__name__ + ".capture_key")
        result.PutCString(
            "installed breakpoint %d at %s+0x%x"
            % (breakpoint.GetID(), module, address)
        )
    except Exception as exc:
        result.SetError(str(exc))


def __lldb_init_module(debugger, _internal_dict):
    debugger.HandleCommand(
        "command script add -f %s.install qqnt-install" % __name__
    )
    print("qqnt-install loaded; key bytes will never be printed")
