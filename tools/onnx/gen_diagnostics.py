#!/usr/bin/env python3

""" Generates PyTorch ONNX Export Diagnostic rules for C++, Python and documentations.
The rules are defined in torch/onnx/_internal/diagnostics/rules.yaml.

Usage:

python -m tools.onnx.gen_diagnostics \
    torch/onnx/_internal/diagnostics/rules.yaml \
    torch/onnx/_internal/diagnostics \
    torch/csrc/onnx/diagnostics/generated \
    torch/docs/source
"""

import argparse
import os
import string
import subprocess
import textwrap
from typing import Any, Mapping, Sequence

import yaml

from torchgen import utils as torchgen_utils

_RULES_GENERATED_COMMENT = """\
GENERATED CODE - DO NOT EDIT DIRECTLY
This file is generated by gen_diagnostics.py.
See tools/onnx/gen_diagnostics.py for more information.

Diagnostic rules for PyTorch ONNX export.
"""

_PY_RULE_CLASS_COMMENT = """\
GENERATED CODE - DO NOT EDIT DIRECTLY
The purpose of generating a class for each rule is to override the `format_message`
method to provide more details in the signature about the format arguments.
"""

_PY_RULE_CLASS_TEMPLATE = """\
class _{pascal_case_name}(infra.Rule):
    \"\"\"{short_description}\"\"\"
    def format_message(  # type: ignore[override]
        self,
        {message_arguments}
    ) -> str:
        \"\"\"Returns the formatted default message of this Rule.

        Message template: {message_template}
        \"\"\"
        return self.message_default_template.format({message_arguments_assigned})

    def format(  # type: ignore[override]
        self,
        level: infra.Level,
        {message_arguments}
    ) -> Tuple[infra.Rule, infra.Level, str]:
        \"\"\"Returns a tuple of (Rule, Level, message) for this Rule.

        Message template: {message_template}
        \"\"\"
        return self, level, self.format_message({message_arguments_assigned})

"""

_PY_RULE_COLLECTION_FIELD_TEMPLATE = """\
{snake_case_name}: _{pascal_case_name} = dataclasses.field(
    default=_{pascal_case_name}.from_sarif(**{sarif_dict}),
    init=False,
)
\"\"\"{short_description}\"\"\"
"""

_CPP_RULE_TEMPLATE = """\
/**
 * @brief {short_description}
 */
{name},
"""

_RuleType = Mapping[str, Any]


def _kebab_case_to_snake_case(name: str) -> str:
    return name.replace("-", "_")


def _kebab_case_to_pascal_case(name: str) -> str:
    return "".join(word.capitalize() for word in name.split("-"))


def _format_rule_for_python_class(rule: _RuleType) -> str:
    pascal_case_name = _kebab_case_to_pascal_case(rule["name"])
    short_description = rule["short_description"]["text"]
    message_template = rule["message_strings"]["default"]["text"]
    field_names = [
        field_name
        for _, field_name, _, _ in string.Formatter().parse(message_template)
        if field_name is not None
    ]
    for field_name in field_names:
        assert isinstance(
            field_name, str
        ), f"Unexpected field type {type(field_name)} from {field_name}. "
        "Field name must be string.\nFull message template: {message_template}"
        assert (
            not field_name.isnumeric()
        ), f"Unexpected numeric field name {field_name}. "
        "Only keyword name formatting is supported.\nFull message template: {message_template}"
    message_arguments = ", ".join(field_names)
    message_arguments_assigned = ", ".join(
        [f"{field_name}={field_name}" for field_name in field_names]
    )
    return _PY_RULE_CLASS_TEMPLATE.format(
        pascal_case_name=pascal_case_name,
        short_description=short_description,
        message_template=repr(message_template),
        message_arguments=message_arguments,
        message_arguments_assigned=message_arguments_assigned,
    )


def _format_rule_for_python_field(rule: _RuleType) -> str:
    snake_case_name = _kebab_case_to_snake_case(rule["name"])
    pascal_case_name = _kebab_case_to_pascal_case(rule["name"])
    short_description = rule["short_description"]["text"]

    return _PY_RULE_COLLECTION_FIELD_TEMPLATE.format(
        snake_case_name=snake_case_name,
        pascal_case_name=pascal_case_name,
        sarif_dict=rule,
        short_description=short_description,
    )


def _format_rule_for_cpp(rule: _RuleType) -> str:
    name = f"k{_kebab_case_to_pascal_case(rule['name'])}"
    short_description = rule["short_description"]["text"]
    return _CPP_RULE_TEMPLATE.format(name=name, short_description=short_description)


def gen_diagnostics_python(
    rules: Sequence[_RuleType], out_py_dir: str, template_dir: str
) -> None:
    rule_class_lines = [_format_rule_for_python_class(rule) for rule in rules]
    rule_field_lines = [_format_rule_for_python_field(rule) for rule in rules]

    fm = torchgen_utils.FileManager(
        install_dir=out_py_dir, template_dir=template_dir, dry_run=False
    )
    fm.write_with_template(
        "_rules.py",
        "rules.py.in",
        lambda: {
            "generated_comment": _RULES_GENERATED_COMMENT,
            "generated_rule_class_comment": _PY_RULE_CLASS_COMMENT,
            "rule_classes": "\n".join(rule_class_lines),
            "rules": textwrap.indent("\n".join(rule_field_lines), " " * 4),
        },
    )
    _lint_file(os.path.join(out_py_dir, "_rules.py"))


def gen_diagnostics_cpp(
    rules: Sequence[_RuleType], out_cpp_dir: str, template_dir: str
) -> None:
    rule_lines = [_format_rule_for_cpp(rule) for rule in rules]
    rule_names = [f'"{_kebab_case_to_snake_case(rule["name"])}",' for rule in rules]

    fm = torchgen_utils.FileManager(
        install_dir=out_cpp_dir, template_dir=template_dir, dry_run=False
    )
    fm.write_with_template(
        "rules.h",
        "rules.h.in",
        lambda: {
            "generated_comment": textwrap.indent(
                _RULES_GENERATED_COMMENT,
                " * ",
                predicate=lambda x: True,  # Don't ignore empty line
            ),
            "rules": textwrap.indent("\n".join(rule_lines), " " * 2),
            "py_rule_names": textwrap.indent("\n".join(rule_names), " " * 4),
        },
    )
    _lint_file(os.path.join(out_cpp_dir, "rules.h"))


def gen_diagnostics_docs(
    rules: Sequence[_RuleType], out_docs_dir: str, template_dir: str
) -> None:
    # TODO: Add doc generation in a follow-up PR.
    pass


def _lint_file(file_path: str) -> None:
    p = subprocess.Popen(["lintrunner", "-a", file_path])
    p.wait()


def gen_diagnostics(
    rules_path: str,
    out_py_dir: str,
    out_cpp_dir: str,
    out_docs_dir: str,
) -> None:
    with open(rules_path, "r") as f:
        rules = yaml.load(f, Loader=torchgen_utils.YamlLoader)

    template_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), "templates")

    gen_diagnostics_python(
        rules,
        out_py_dir,
        template_dir,
    )

    gen_diagnostics_cpp(
        rules,
        out_cpp_dir,
        template_dir,
    )

    gen_diagnostics_docs(rules, out_docs_dir, template_dir)


def main() -> None:
    parser = argparse.ArgumentParser(description="Generate ONNX diagnostics files")
    parser.add_argument("rules_path", metavar="RULES", help="path to rules.yaml")
    parser.add_argument(
        "out_py_dir",
        metavar="OUT_PY",
        help="path to output directory for Python",
    )
    parser.add_argument(
        "out_cpp_dir",
        metavar="OUT_CPP",
        help="path to output directory for C++",
    )
    parser.add_argument(
        "out_docs_dir",
        metavar="OUT_DOCS",
        help="path to output directory for docs",
    )
    args = parser.parse_args()
    gen_diagnostics(
        args.rules_path,
        args.out_py_dir,
        args.out_cpp_dir,
        args.out_docs_dir,
    )


if __name__ == "__main__":
    main()
