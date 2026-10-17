"""Physical and code-bearing Python lines under <root>/src/slidemage (see docs/STREAMLINING_PLAN.md)."""
import ast
import io
import pathlib
import sys
import tokenize

root = pathlib.Path(sys.argv[1] if len(sys.argv) > 1 else ".") / "src" / "slidemage"
physical = code = files = 0
for path in sorted(root.rglob("*.py")):
    if "__pycache__" in path.parts:
        continue
    src = path.read_text(encoding="utf-8")
    files += 1
    physical += len(src.splitlines())
    lines = set()
    for tok in tokenize.generate_tokens(io.StringIO(src).readline):
        if tok.type in (tokenize.COMMENT, tokenize.NL, tokenize.NEWLINE, tokenize.INDENT,
                        tokenize.DEDENT, tokenize.ENDMARKER):
            continue
        lines.update(range(tok.start[0], tok.end[0] + 1))
    docs = set()
    for node in ast.walk(ast.parse(src)):
        if isinstance(node, (ast.Module, ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef)) and node.body:
            first = node.body[0]
            if isinstance(first, ast.Expr) and isinstance(getattr(first, "value", None), ast.Constant) \
                    and isinstance(first.value.value, str):
                docs.update(range(first.lineno, first.end_lineno + 1))
    code += len(lines - docs)
print(f"files={files} physical={physical} code={code}")
