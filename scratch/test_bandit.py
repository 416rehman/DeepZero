import subprocess

def test_p(cmd):
    # variable cmd -> B603
    subprocess.run(cmd)

def test_literal(arg):
    # string literal first elem
    subprocess.run(["hello", arg])

def test_shutil(cmd):
    import shutil
    cmd[0] = shutil.which(cmd[0]) or cmd[0]
    subprocess.run(cmd)

