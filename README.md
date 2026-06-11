# Wall Library Builder

A pyRevit tool for creating and updating Revit Basic Wall Types from structured CSV wall library data.

The project explores how external BIM standards can be translated into native Revit content through configurable mapping, validation, and automated type generation workflows.

## Why I Built This

Different BIM teams often maintain wall libraries using different naming conventions, templates, and standards.

This project explores a workflow for translating structured external wall definitions into native Revit wall types through configurable mapping and validation.

The goal was not simply to automate wall creation, but to experiment with how external BIM content can be standardized and integrated into Revit environments with minimal manual work.

## Features

- Create Revit Basic Wall Types from CSV data
- Update existing wall types
- Create renamed copies when wall types already exist
- Generate compound wall structures from layer definitions
- Configurable column mapping
- Optional type parameter mapping
- Validation before model changes
- Preview ready, warning, and error states
- Result reporting through pyRevit
- CSV template generation

## Workflow

```text
CSV Wall Library
        ↓
Column Mapping
        ↓
Validation
        ↓
Preview
        ↓
Create / Update
        ↓
Native Revit Basic Wall Types