# -*- coding: utf-8 -*-
"""
Wall Library Builder - pyRevit
Creates / updates Revit Basic Wall Types from a controlled CSV template or a custom mapped CSV.

Scope:
- Required mapping: wall type name, layer order, function, material, thickness.
- Optional mapping: core layer marker + any writable Wall Type parameter selected by the user.
- Wraps mapping intentionally removed for a cleaner and safer V1 scope.
"""

import os
import csv
import traceback

import clr
clr.AddReference('PresentationFramework')
clr.AddReference('PresentationCore')
clr.AddReference('WindowsBase')
clr.AddReference('System')

from System.Collections.ObjectModel import ObservableCollection
from System.Windows import Thickness, VerticalAlignment, Visibility
from System.Windows.Controls import StackPanel, DockPanel, CheckBox, ComboBox, TextBlock, Dock
from Microsoft.Win32 import SaveFileDialog
from pyrevit import revit, DB, forms, script

uidoc = revit.uidoc
doc = revit.doc
output = script.get_output()

BUNDLE_DIR = os.path.dirname(__file__)
DEFAULT_CSV = os.path.join(BUNDLE_DIR, 'WallLibrary_Template.csv')
XAML_FILE = os.path.join(BUNDLE_DIR, 'WallLibraryBuilder.xaml')

GREEN = '#00D63F'

# Performance caches: built once per tool run, instead of scanning the whole Revit model repeatedly.
_BASIC_WALL_TYPES_CACHE = None
_WALL_TYPE_NAME_CACHE = None
_MATERIAL_CACHE = None


INTERNAL_FIELDS = [
    'wall_type_name',
    'layer_order',
    'function',
    'material_name',
    'thickness_mm',
    'is_core'
]

FIELD_LABELS = {
    'wall_type_name': 'Wall Type Name',
    'layer_order': 'Layer Order',
    'function': 'Layer Function',
    'material_name': 'Material Name',
    'thickness_mm': 'Thickness mm',
    'is_core': 'Core'
}

FUNCTION_MAP = {
    'structure': DB.MaterialFunctionAssignment.Structure,
    'structural': DB.MaterialFunctionAssignment.Structure,
    'substrate': DB.MaterialFunctionAssignment.Substrate,
    'thermalairlayer': DB.MaterialFunctionAssignment.Insulation,
    'thermalair': DB.MaterialFunctionAssignment.Insulation,
    'thermal/airlayer': DB.MaterialFunctionAssignment.Insulation,
    'thermal/air layer': DB.MaterialFunctionAssignment.Insulation,
    'thermal air layer': DB.MaterialFunctionAssignment.Insulation,
    'insulation': DB.MaterialFunctionAssignment.Insulation,
    'finish1': DB.MaterialFunctionAssignment.Finish1,
    'finish 1': DB.MaterialFunctionAssignment.Finish1,
    'finish2': DB.MaterialFunctionAssignment.Finish2,
    'finish 2': DB.MaterialFunctionAssignment.Finish2,
    'membranelayer': DB.MaterialFunctionAssignment.Membrane,
    'membrane layer': DB.MaterialFunctionAssignment.Membrane,
    'membrane': DB.MaterialFunctionAssignment.Membrane,
}

YES_VALUES = set(['yes', 'y', 'true', '1', 'x', 'evet', 'core'])

COMMON_OPTIONAL_PARAM_ORDER = [
    'Type Comments',
    'Description',
    'Fire Rating',
    'Keynote',
    'Assembly Code',
    'Assembly Description',
    'Manufacturer',
    'Model',
    'Cost',
    'URL'
]

OPTIONAL_PARAM_CANDIDATES = {
    'Type Comments': ['TypeComments', 'Type Comments', 'Comments', 'Type_Comments'],
    'Description': ['Description', 'TypeDescription', 'Type Description'],
    'Fire Rating': ['FireRating', 'Fire Rating', 'Fire_Rating'],
    'Keynote': ['Keynote', 'Key Note'],
    'Assembly Code': ['AssemblyCode', 'Assembly Code', 'Assembly_Code'],
    'Assembly Description': ['AssemblyDescription', 'Assembly Description', 'Assembly_Description'],
    'Manufacturer': ['Manufacturer', 'Maker', 'Brand'],
    'Model': ['Model', 'ModelNumber', 'Model Number'],
    'Cost': ['Cost', 'Unit Cost'],
    'URL': ['URL', 'Link', 'Product URL']
}


def safe_name(elem):
    try:
        return DB.Element.Name.GetValue(elem)
    except Exception:
        try:
            return elem.Name
        except Exception:
            return '<Unnamed>'


def normalize(value):
    if value is None:
        return ''
    return str(value).strip()


def norm_key(value):
    return normalize(value).lower().replace(' ', '').replace('_', '').replace('-', '').replace('/', '').replace('(', '').replace(')', '')


def yes(value):
    return normalize(value).lower() in YES_VALUES


def parse_float(value, default=0.0):
    text = normalize(value).replace(',', '.')
    if not text:
        return default
    try:
        return float(text)
    except Exception:
        return default


def is_number(value):
    try:
        float(normalize(value).replace(',', '.'))
        return True
    except Exception:
        return False


def mm_to_internal(mm):
    try:
        return DB.UnitUtils.ConvertToInternalUnits(float(mm), DB.UnitTypeId.Millimeters)
    except Exception:
        return float(mm) / 304.8


def refresh_wall_type_cache():
    global _BASIC_WALL_TYPES_CACHE, _WALL_TYPE_NAME_CACHE
    wall_types = []
    all_types = DB.FilteredElementCollector(doc).OfClass(DB.WallType).ToElements()
    for wt in all_types:
        try:
            if wt.Kind == DB.WallKind.Basic:
                wall_types.append(wt)
        except Exception:
            pass
    wall_types = sorted(wall_types, key=lambda wt: safe_name(wt).lower())
    _BASIC_WALL_TYPES_CACHE = wall_types
    _WALL_TYPE_NAME_CACHE = dict((safe_name(wt).lower(), wt) for wt in wall_types)
    return wall_types


def get_basic_wall_types(force_refresh=False):
    global _BASIC_WALL_TYPES_CACHE
    if force_refresh or _BASIC_WALL_TYPES_CACHE is None:
        return refresh_wall_type_cache()
    return _BASIC_WALL_TYPES_CACHE


def get_basic_wall_type_by_name(name):
    lname = normalize(name).lower()
    if not lname:
        return None
    if _WALL_TYPE_NAME_CACHE is None:
        refresh_wall_type_cache()
    return _WALL_TYPE_NAME_CACHE.get(lname)


def register_wall_type_in_cache(wall_type):
    global _BASIC_WALL_TYPES_CACHE, _WALL_TYPE_NAME_CACHE
    if not wall_type:
        return
    if _BASIC_WALL_TYPES_CACHE is None or _WALL_TYPE_NAME_CACHE is None:
        refresh_wall_type_cache()
        return
    name_key = safe_name(wall_type).lower()
    _WALL_TYPE_NAME_CACHE[name_key] = wall_type
    if wall_type not in _BASIC_WALL_TYPES_CACHE:
        _BASIC_WALL_TYPES_CACHE.append(wall_type)
        _BASIC_WALL_TYPES_CACHE = sorted(_BASIC_WALL_TYPES_CACHE, key=lambda wt: safe_name(wt).lower())


def refresh_material_cache():
    global _MATERIAL_CACHE
    _MATERIAL_CACHE = {}
    mats = DB.FilteredElementCollector(doc).OfClass(DB.Material).ToElements()
    for mat in mats:
        try:
            _MATERIAL_CACHE[safe_name(mat).lower()] = mat.Id
        except Exception:
            pass
    return _MATERIAL_CACHE


def get_material_id_by_name(name):
    name = normalize(name)
    if not name:
        return DB.ElementId.InvalidElementId
    if _MATERIAL_CACHE is None:
        refresh_material_cache()
    return _MATERIAL_CACHE.get(name.lower(), DB.ElementId.InvalidElementId)


def read_csv_raw(csv_path):
    if not os.path.exists(csv_path):
        raise Exception('CSV file not found: {0}'.format(csv_path))

    with open(csv_path, 'rb') as f:
        sample = f.read(4096)

    dialect = None
    try:
        dialect = csv.Sniffer().sniff(sample)
    except Exception:
        dialect = csv.excel

    rows = []
    with open(csv_path, 'rb') as f:
        reader = csv.DictReader(f, dialect=dialect)
        headers = reader.fieldnames or []
        headers = [normalize(h) for h in headers]
        for raw in reader:
            fixed = {}
            for k, v in raw.items():
                fixed[normalize(k)] = normalize(v)
            rows.append(fixed)
    return headers, rows


def auto_pick(headers, candidates):
    if not headers:
        return None
    pairs = [(h, norm_key(h)) for h in headers]

    for c in candidates:
        nc = norm_key(c)
        for h, nh in pairs:
            if nh == nc:
                return h

    for c in candidates:
        nc = norm_key(c)
        for h, nh in pairs:
            if nc and (nc in nh or nh in nc):
                return h

    return None


def map_rows(raw_rows, mapping, optional_mapping):
    mapped = []
    for i, r in enumerate(raw_rows):
        item = {'_source_row': i + 2, '_params': {}}
        for field in INTERNAL_FIELDS:
            col = mapping.get(field)
            item[field] = normalize(r.get(col)) if col else ''

        for pname, col in optional_mapping.items():
            if col:
                val = normalize(r.get(col))
                if val:
                    item['_params'][pname] = val
        mapped.append(item)
    return mapped


def group_mapped_rows(mapped_rows):
    grouped = {}
    for row in mapped_rows:
        tname = row.get('wall_type_name')
        if not tname:
            continue
        grouped.setdefault(tname, []).append(row)

    for tname in grouped:
        grouped[tname] = sorted(grouped[tname], key=lambda r: parse_float(r.get('layer_order'), 0))
    return grouped


def first_issue(errors, warnings):
    if errors:
        return errors[0]
    if warnings:
        return warnings[0]
    return '-'


def validate_group(type_name, rows):
    errors = []
    warnings = []

    if not type_name:
        errors.append('Missing wall type name')

    if not rows:
        errors.append('No layer rows found')
        return errors, warnings

    order_values = []
    has_structure = False
    has_core = False

    for row in rows:
        rowno = row.get('_source_row')
        order = row.get('layer_order')
        thk = row.get('thickness_mm')
        fn = row.get('function')
        mat = row.get('material_name')

        if not is_number(order):
            errors.append('Row {0}: layer order is not numeric'.format(rowno))
        else:
            order_values.append(int(parse_float(order, 0)))

        if not fn:
            warnings.append('Row {0}: layer function is empty; Substrate will be used'.format(rowno))

        fn_key = norm_key(fn)
        is_membrane = fn_key in ['membranelayer', 'membrane']
        if fn_key in ['structure', 'structural']:
            has_structure = True

        if yes(row.get('is_core')):
            has_core = True

        if not is_number(thk):
            errors.append('Row {0}: thickness is not numeric'.format(rowno))
        else:
            thickness = parse_float(thk, 0)
            if thickness <= 0 and not is_membrane:
                errors.append('Row {0}: thickness must be greater than 0 except membrane layers'.format(rowno))
            if is_membrane and thickness != 0:
                warnings.append('Row {0}: membrane layer thickness will be forced to 0'.format(rowno))

        if mat and get_material_id_by_name(mat) == DB.ElementId.InvalidElementId:
            warnings.append('Row {0}: material not found: {1}'.format(rowno, mat))
        if not mat:
            warnings.append('Row {0}: material is empty'.format(rowno))

    if len(order_values) != len(set(order_values)):
        warnings.append('Duplicate layer order values found')

    if not has_structure:
        warnings.append('No Structure layer detected')

    if not has_core:
        warnings.append('Core not defined')

    return errors, warnings


def make_layer(row):
    function_text = norm_key(row.get('function'))
    material_name = normalize(row.get('material_name'))
    thickness_mm = parse_float(row.get('thickness_mm'), 0.0)

    func = FUNCTION_MAP.get(function_text, DB.MaterialFunctionAssignment.Substrate)
    mat_id = get_material_id_by_name(material_name)
    width = mm_to_internal(thickness_mm)

    if func == DB.MaterialFunctionAssignment.Membrane:
        width = 0.0

    return DB.CompoundStructureLayer(width, func, mat_id)


def set_wall_compound_structure(wall_type, rows):
    if wall_type.Kind != DB.WallKind.Basic:
        raise Exception('Only Basic Wall types can be edited by this tool.')

    layers = [make_layer(row) for row in rows]
    if not layers:
        raise Exception('No layers found for {0}'.format(safe_name(wall_type)))

    cs = DB.CompoundStructure.CreateSimpleCompoundStructure(layers)

    try:
        core_indices = []
        for idx, row in enumerate(rows):
            if yes(row.get('is_core')):
                core_indices.append(idx)
        if core_indices:
            first_core = min(core_indices)
            last_core = max(core_indices)
            cs.SetNumberOfShellLayers(DB.ShellLayerType.Exterior, first_core)
            cs.SetNumberOfShellLayers(DB.ShellLayerType.Interior, len(rows) - last_core - 1)
    except Exception:
        pass

    wall_type.SetCompoundStructure(cs)


# Robust optional type parameter resolver.
# Revit UI parameter names can be localized or exposed through built-in parameters.
# This resolver first tries known BuiltInParameter ids, then falls back to exact and normalized name lookup.
OPTIONAL_BUILTIN_PARAM_CANDIDATES = {
    'Type Comments': ['ALL_MODEL_TYPE_COMMENTS'],
    'Description': ['ALL_MODEL_DESCRIPTION'],
    'Fire Rating': ['FIRE_RATING'],
    'Keynote': ['KEYNOTE_PARAM'],
    'Assembly Code': ['UNIFORMAT_CODE'],
    'Assembly Description': ['UNIFORMAT_DESCRIPTION'],
    'Manufacturer': ['ALL_MODEL_MANUFACTURER'],
    'Model': ['ALL_MODEL_MODEL'],
    'Cost': ['ALL_MODEL_COST'],
    'URL': ['ALL_MODEL_URL'],
}


def get_builtin_parameter(elem, builtin_name):
    try:
        bip = getattr(DB.BuiltInParameter, builtin_name)
    except Exception:
        return None
    try:
        return elem.get_Parameter(bip)
    except Exception:
        return None


def get_param_by_name(elem, param_name):
    # 1) Try mapped built-in parameters first.
    for builtin_name in OPTIONAL_BUILTIN_PARAM_CANDIDATES.get(param_name, []):
        p = get_builtin_parameter(elem, builtin_name)
        if p:
            return p

    wanted = normalize(param_name)
    wanted_key = norm_key(wanted)

    # 2) Exact display name lookup.
    for p in elem.Parameters:
        try:
            if p.Definition and normalize(p.Definition.Name) == wanted:
                return p
        except Exception:
            pass

    # 3) Normalized display name lookup.
    for p in elem.Parameters:
        try:
            if p.Definition and norm_key(p.Definition.Name) == wanted_key:
                return p
        except Exception:
            pass

    # 4) Candidate aliases lookup.
    for alias in OPTIONAL_PARAM_CANDIDATES.get(param_name, []):
        alias_key = norm_key(alias)
        for p in elem.Parameters:
            try:
                if p.Definition and norm_key(p.Definition.Name) == alias_key:
                    return p
            except Exception:
                pass

    return None


def set_parameter_from_text(elem, param_name, value):
    value = normalize(value)
    if not value:
        return None

    p = get_param_by_name(elem, param_name)
    if not p:
        return 'Parameter not found: {0}'.format(param_name)
    if p.IsReadOnly:
        return 'Parameter is read-only: {0}'.format(param_name)

    try:
        st = p.StorageType
        if st == DB.StorageType.String:
            p.Set(value)
        elif st == DB.StorageType.Integer:
            if yes(value):
                p.Set(1)
            elif normalize(value).lower() in ['no', 'n', 'false', '0', 'hayir', 'hayır']:
                p.Set(0)
            elif is_number(value):
                p.Set(int(parse_float(value, 0)))
            else:
                return 'Integer parameter value is not numeric: {0} = {1}'.format(param_name, value)
        elif st == DB.StorageType.Double:
            if is_number(value):
                p.Set(parse_float(value, 0.0))
            else:
                return 'Double parameter value is not numeric: {0} = {1}'.format(param_name, value)
        elif st == DB.StorageType.ElementId:
            # Some classification-like parameters can be ElementId-backed.
            # SetValueString is the safest generic attempt; if Revit refuses it, report clearly.
            try:
                if not p.SetValueString(value):
                    return 'ElementId parameter could not accept text value: {0} = {1}'.format(param_name, value)
            except Exception:
                return 'ElementId parameter is not text-settable: {0} = {1}'.format(param_name, value)
        else:
            return 'Unsupported parameter storage type: {0}'.format(param_name)
    except Exception as ex:
        return 'Could not set parameter {0}: {1}'.format(param_name, str(ex))

    return None


def get_first_optional_param_value(rows, param_name):
    for row in rows:
        try:
            val = normalize(row.get('_params', {}).get(param_name, ''))
            if val:
                return val
        except Exception:
            pass
    return ''


def clear_parameter_value(elem, param_name):
    p = get_param_by_name(elem, param_name)
    if not p:
        return None
    if p.IsReadOnly:
        return 'Could not clear read-only parameter: {0}'.format(param_name)

    try:
        st = p.StorageType
        if st == DB.StorageType.String:
            p.Set('')
        elif st == DB.StorageType.Integer:
            p.Set(0)
        elif st == DB.StorageType.Double:
            p.Set(0.0)
        elif st == DB.StorageType.ElementId:
            # Do not force-clear ElementId-backed parameters; report only if needed by future debugging.
            return None
        else:
            return None
    except Exception as ex:
        return 'Could not clear parameter {0}: {1}'.format(param_name, str(ex))
    return None


def clear_unselected_or_empty_optional_parameters(wall_type, rows, selected_param_names):
    """Prevent duplicated wall types from inheriting metadata from the source/template wall.

    Revit Duplicate() copies type parameters from the source type. For newly created or renamed-copy
    wall types, metadata should be controlled only by the selected Optional Mapping fields and CSV data.
    Therefore common optional parameters are cleared when they are not selected, or when selected but no
    CSV value exists for that wall type.
    """
    messages = []
    selected = set(selected_param_names or [])
    for pname in COMMON_OPTIONAL_PARAM_ORDER:
        should_clear = (pname not in selected) or (not get_first_optional_param_value(rows, pname))
        if should_clear:
            msg = clear_parameter_value(wall_type, pname)
            if msg:
                messages.append(msg)
    return messages


def apply_optional_parameters(wall_type, rows, selected_param_names):
    messages = []
    if not selected_param_names:
        return messages

    for pname in selected_param_names:
        val = get_first_optional_param_value(rows, pname)
        if not val:
            continue
        msg = set_parameter_from_text(wall_type, pname, val)
        if msg:
            messages.append(msg)
    return messages


def validate_optional_param_consistency(rows, selected_param_names):
    warnings = []
    for pname in selected_param_names or []:
        values = []
        for row in rows:
            val = normalize(row.get('_params', {}).get(pname, ''))
            if val:
                values.append(val)
        unique_vals = []
        seen = set()
        for val in values:
            key = norm_key(val)
            if key not in seen:
                seen.add(key)
                unique_vals.append(val)
        if len(unique_vals) > 1:
            warnings.append('Optional parameter {0} has different values across layer rows; first non-empty value will be used'.format(pname))
    return warnings


def make_renamed_copy_name(type_name, rename_affix_mode, rename_affix_text):
    affix = normalize(rename_affix_text)
    if not affix:
        affix = ' - Imported'

    mode = normalize(rename_affix_mode).lower()
    if 'prefix' in mode:
        base_name = affix + type_name
    else:
        base_name = type_name + affix

    new_name = base_name
    n = 1
    while get_basic_wall_type_by_name(new_name):
        n += 1
        new_name = '{0} {1:02d}'.format(base_name, n)
    return new_name


def create_or_update_wall_type(type_name, rows, template_wt, mode, selected_param_names, rename_affix_mode='Suffix', rename_affix_text=' - Imported'):
    existing = get_basic_wall_type_by_name(type_name)

    if existing and mode == 'skip':
        return 'SKIPPED', safe_name(existing), []

    if existing and mode == 'update':
        target = existing
        set_wall_compound_structure(target, rows)
        register_wall_type_in_cache(target)
        param_msgs = apply_optional_parameters(target, rows, selected_param_names)
        return 'UPDATED', safe_name(target), param_msgs

    if existing and mode == 'rename':
        new_name = make_renamed_copy_name(type_name, rename_affix_mode, rename_affix_text)
        target = template_wt.Duplicate(new_name)
        set_wall_compound_structure(target, rows)
        register_wall_type_in_cache(target)
        param_msgs = []
        param_msgs.extend(clear_unselected_or_empty_optional_parameters(target, rows, selected_param_names))
        param_msgs.extend(apply_optional_parameters(target, rows, selected_param_names))
        return 'CREATED_RENAMED', safe_name(target), param_msgs

    if not existing:
        target = template_wt.Duplicate(type_name)
        set_wall_compound_structure(target, rows)
        register_wall_type_in_cache(target)
        param_msgs = []
        param_msgs.extend(clear_unselected_or_empty_optional_parameters(target, rows, selected_param_names))
        param_msgs.extend(apply_optional_parameters(target, rows, selected_param_names))
        return 'CREATED', safe_name(target), param_msgs

    return 'UNKNOWN', type_name, ['Unhandled condition']


class WallPreviewRow(object):
    def __init__(self, name, layer_count, total_mm, status, message):
        self.Import = (status != 'ERROR')
        self.TypeName = name
        self.LayerCount = layer_count
        self.TotalThickness = '{0:.1f}'.format(total_mm)
        self.Status = status
        self.Message = message


class OptionalParamControl(object):
    def __init__(self, param_name, checkbox, combo):
        self.param_name = param_name
        self.checkbox = checkbox
        self.combo = combo


class WallLibraryBuilderWindow(forms.WPFWindow):
    def __init__(self):
        forms.WPFWindow.__init__(self, XAML_FILE)

        self.headers = []
        self.raw_rows = []
        self.mapped_rows = []
        self.wall_data = {}
        self.validation = {}
        self.rows = ObservableCollection[object]()
        self.optional_controls = []
        self.optional_param_names = []

        self.basic_wall_types = get_basic_wall_types()
        self.baseWallCombo.ItemsSource = [safe_name(wt) for wt in self.basic_wall_types]
        if self.basic_wall_types:
            self.baseWallCombo.SelectedIndex = 0

        self.csvPathBox.Text = DEFAULT_CSV
        self.modeCombo.SelectedIndex = 0
        try:
            self.renameAffixModeCombo.SelectedIndex = 1
            self.renameAffixTextBox.Text = ' - Imported'
        except Exception:
            pass
        self.previewGrid.ItemsSource = self.rows
        self.statusText.Text = ''
        self.summaryText.Text = 'No data loaded.'

        # Fast startup: do not scan wall type parameters while opening the window.
        # Start with the common parameter list; the Refresh button can scan project parameters on demand.
        self.optional_param_names = list(COMMON_OPTIONAL_PARAM_ORDER)
        self.build_optional_parameter_ui()
        self.update_rename_options_visibility()


    def mode_changed(self, sender, args):
        self.update_rename_options_visibility()

    def update_rename_options_visibility(self):
        try:
            content = self.modeCombo.SelectedItem.Content.ToString().lower()
            visible = Visibility.Visible if ('renamed' in content or 'copy' in content) else Visibility.Collapsed
            self.renameAffixModeCombo.Visibility = visible
            self.renameAffixTextBox.Visibility = visible
        except Exception:
            pass

    def generate_template(self, sender, args):
        dlg = SaveFileDialog()
        dlg.Title = 'Save Wall Library CSV Template'
        dlg.Filter = 'CSV files (*.csv)|*.csv'
        dlg.FileName = 'WallLibrary_Template.csv'
        if not dlg.ShowDialog():
            return

        headers = ['TypeName', 'LayerOrder', 'Function', 'MaterialName', 'Thickness_mm', 'IsCore']
        for pname in COMMON_OPTIONAL_PARAM_ORDER:
            clean = pname.replace(' ', '')
            if clean not in headers:
                headers.append(clean)

        # Blank template with only headers. User can fill it in Excel and save as CSV.
        with open(dlg.FileName, 'wb') as f:
            writer = csv.writer(f)
            writer.writerow(headers)

        self.csvPathBox.Text = dlg.FileName
        self.statusText.Text = 'Template created. Fill it, then load/preview data.'
        forms.alert('Blank CSV template saved:\n{0}'.format(dlg.FileName), title='Wall Library Builder')

    def browse_csv(self, sender, args):
        path = forms.pick_file(file_ext='csv', title='Select Wall Library CSV')
        if path:
            self.csvPathBox.Text = path
            self.statusText.Text = 'CSV selected. Click Preview Data.'

    def load_data(self):
        self.headers, self.raw_rows = read_csv_raw(self.csvPathBox.Text)
        self.populate_mapping_combos()
        self.auto_map(None, None)
        self.rows.Clear()
        self.wall_data = {}
        self.validation = {}
        self.summaryText.Text = 'Loaded {0} column(s), {1} row(s).'.format(len(self.headers), len(self.raw_rows))
        self.statusText.Text = 'Data loaded. Review mapping, then preview.'

    def populate_mapping_combos(self):
        combos = [self.mapType, self.mapOrder, self.mapFunction, self.mapMaterial, self.mapThickness]
        for cb in combos:
            cb.ItemsSource = self.headers

        for opc in self.optional_controls:
            opc.combo.ItemsSource = self.headers

    def auto_map(self, sender, args):
        if not self.headers:
            try:
                self.headers, self.raw_rows = read_csv_raw(self.csvPathBox.Text)
                self.populate_mapping_combos()
            except Exception:
                return

        config = [
            (self.mapType, ['TypeName', 'WallType', 'Wall Type', 'Type Name', 'Assembly Name', 'AssemblyName']),
            (self.mapOrder, ['LayerOrder', 'Layer Order', 'Order', 'Layer No', 'LayerNumber']),
            (self.mapFunction, ['Function', 'Layer Function', 'Material Function']),
            (self.mapMaterial, ['MaterialName', 'Material Name', 'Material']),
            (self.mapThickness, ['Thickness_mm', 'Thickness mm', 'Width_mm', 'Width', 'Thickness']),
        ]
        for cb, candidates in config:
            picked = auto_pick(self.headers, candidates)
            if picked:
                cb.SelectedItem = picked

        # Optional: core is not a Revit type parameter; it is a layer marker.
        # It is auto-consumed if the CSV has IsCore/Core even though it is not shown in the required panel.
        for opc in self.optional_controls:
            candidates = OPTIONAL_PARAM_CANDIDATES.get(opc.param_name, [opc.param_name, opc.param_name.replace(' ', '')])
            picked = auto_pick(self.headers, candidates)
            if picked:
                opc.combo.SelectedItem = picked
                # Enable only the most common direct match by default to avoid over-mapping surprises.
                if opc.param_name == 'Type Comments':
                    opc.checkbox.IsChecked = True

        self.statusText.Text = 'Columns auto-mapped. Review before creating wall types.'

    def get_mapping(self):
        # Core column is optional and auto-detected from source headers.
        core_col = auto_pick(self.headers, ['IsCore', 'Is Core', 'Core'])
        return {
            'wall_type_name': self.mapType.SelectedItem,
            'layer_order': self.mapOrder.SelectedItem,
            'function': self.mapFunction.SelectedItem,
            'material_name': self.mapMaterial.SelectedItem,
            'thickness_mm': self.mapThickness.SelectedItem,
            'is_core': core_col,
        }

    def get_optional_mapping(self):
        result = {}
        for opc in self.optional_controls:
            try:
                if opc.checkbox.IsChecked and opc.combo.SelectedItem:
                    result[opc.param_name] = opc.combo.SelectedItem
            except Exception:
                pass
        return result

    def validate_mapping(self, mapping):
        required = ['wall_type_name', 'layer_order', 'function', 'material_name', 'thickness_mm']
        missing = []
        for field in required:
            if not mapping.get(field):
                missing.append(FIELD_LABELS[field])
        if missing:
            raise Exception('Required mapping missing: {0}'.format(', '.join(missing)))

    def preview_data(self, sender, args):
        try:
            self.load_data()
            # Build material cache once before validation.
            refresh_material_cache()
            mapping = self.get_mapping()
            self.validate_mapping(mapping)
            optional_mapping = self.get_optional_mapping()

            self.mapped_rows = map_rows(self.raw_rows, mapping, optional_mapping)
            self.wall_data = group_mapped_rows(self.mapped_rows)
            self.validation = {}
            self.rows.Clear()

            ok_count = 0
            warning_count = 0
            error_count = 0

            for tname in sorted(self.wall_data.keys(), key=lambda x: x.lower()):
                layers = self.wall_data[tname]
                total = sum([parse_float(r.get('thickness_mm'), 0) for r in layers])
                errors, warnings = validate_group(tname, layers)
                warnings.extend(validate_optional_param_consistency(layers, optional_mapping.keys()))
                self.validation[tname] = {'errors': errors, 'warnings': warnings}

                if errors:
                    status = 'ERROR'
                    error_count += 1
                elif warnings:
                    status = 'WARNING'
                    warning_count += 1
                else:
                    status = 'READY'
                    ok_count += 1

                self.rows.Add(WallPreviewRow(tname, len(layers), total, status, first_issue(errors, warnings)))

            self.summaryText.Text = '{0} ready\n{1} warning\n{2} error\n{3} wall type(s)'.format(ok_count, warning_count, error_count, len(self.wall_data))
            self.statusText.Text = 'Preview generated. Errors are not selected.'
        except Exception as ex:
            self.statusText.Text = 'Preview failed.'
            forms.alert(str(ex), title='Wall Library Builder - Preview Error')

    def show_issues(self, sender, args):
        if not self.validation:
            forms.alert('Preview data first.', title='Wall Library Builder')
            return
        output.print_md('## Wall Library Builder Validation Report')
        found = False
        for name in sorted(self.validation.keys(), key=lambda x: x.lower()):
            errors = self.validation[name]['errors']
            warnings = self.validation[name]['warnings']
            if not errors and not warnings:
                continue
            found = True
            output.print_md('### {0}'.format(name))
            for e in errors:
                output.print_md('- **ERROR:** {0}'.format(e))
            for w in warnings:
                output.print_md('- WARNING: {0}'.format(w))
        if not found:
            output.print_md('No issues found.')
        forms.alert('Validation report printed to pyRevit output panel.', title='Wall Library Builder')

    def toggle_selection(self, sender, args):
        any_selected = False
        for row in self.rows:
            if row.Import:
                any_selected = True
                break

        if any_selected:
            for row in self.rows:
                row.Import = False
        else:
            for row in self.rows:
                row.Import = (row.Status != 'ERROR')

        self.previewGrid.Items.Refresh()

    def refresh_parameters(self, sender, args):
        try:
            self.optional_param_names = self.collect_wall_type_parameters()
            self.build_optional_parameter_ui()
            if self.headers:
                self.populate_mapping_combos()
                self.auto_map(None, None)
            pass
        except Exception as ex:
            pass
            output.print_md('Optional parameter refresh failed: {0}'.format(str(ex)))

    def collect_wall_type_parameters(self):
        names = []
        seen = set()

        def add_name(n):
            if not n:
                return
            key = n.lower()
            if key not in seen:
                seen.add(key)
                names.append(n)

        # Prefer common parameters first.
        for n in COMMON_OPTIONAL_PARAM_ORDER:
            add_name(n)

        # Add writable type parameters from basic wall types in the current model.
        for wt in self.basic_wall_types[:8]:
            try:
                for p in wt.Parameters:
                    try:
                        if p.IsReadOnly:
                            continue
                        if not p.Definition:
                            continue
                        pname = p.Definition.Name
                        if pname in ['Type Name', 'Family Name']:
                            continue
                        add_name(pname)
                    except Exception:
                        pass
            except Exception:
                pass

        return names

    def build_optional_parameter_ui(self):
        self.optionalParamsPanel.Children.Clear()
        self.optional_controls = []

        for pname in self.optional_param_names:
            row = DockPanel()
            row.Margin = Thickness(0, 0, 0, 8)
            row.LastChildFill = False

            cb = CheckBox()
            cb.Width = 24
            cb.VerticalAlignment = VerticalAlignment.Center
            DockPanel.SetDock(cb, Dock.Left)
            row.Children.Add(cb)

            label = TextBlock()
            label.Text = pname
            label.Width = 94
            label.VerticalAlignment = VerticalAlignment.Center
            DockPanel.SetDock(label, Dock.Left)
            row.Children.Add(label)

            combo = ComboBox()
            combo.Width = 102
            combo.ItemsSource = self.headers
            DockPanel.SetDock(combo, Dock.Right)
            row.Children.Add(combo)

            self.optionalParamsPanel.Children.Add(row)
            self.optional_controls.append(OptionalParamControl(pname, cb, combo))

    def create_walls(self, sender, args):
        if not self.wall_data:
            forms.alert('Preview the data first.', title='Wall Library Builder')
            return

        if not self.basic_wall_types:
            forms.alert('No Basic Wall type found in this project. Create one Basic Wall manually first.', title='Wall Library Builder')
            return

        idx = self.baseWallCombo.SelectedIndex
        if idx < 0 or idx >= len(self.basic_wall_types):
            idx = 0
        template_wt = self.basic_wall_types[idx]

        if template_wt.Kind != DB.WallKind.Basic:
            forms.alert('Selected base wall is not a Basic Wall.', title='Wall Library Builder')
            return

        mode = 'update'
        try:
            content = self.modeCombo.SelectedItem.Content.ToString().lower()
            if 'skip' in content:
                mode = 'skip'
            elif 'renamed' in content or 'copy' in content:
                mode = 'rename'
        except Exception:
            pass

        selected = []
        for row in self.rows:
            if row.Import:
                selected.append(row.TypeName)

        if not selected:
            forms.alert('No wall types selected.', title='Wall Library Builder')
            return

        blocked = []
        for name in selected:
            if self.validation.get(name, {}).get('errors'):
                blocked.append(name)
        if blocked:
            forms.alert('Some selected wall types still have errors and will not be created:\n{0}'.format('\n'.join(blocked)), title='Wall Library Builder')
            return

        # Rebuild mapped rows with the CURRENT optional mapping before creation.
        # This avoids losing type parameter values when the user changes optional checkboxes
        # after Preview Data but before Create / Update.
        try:
            current_mapping = self.get_mapping()
            current_optional_mapping = self.get_optional_mapping()
            self.mapped_rows = map_rows(self.raw_rows, current_mapping, current_optional_mapping)
            self.wall_data = group_mapped_rows(self.mapped_rows)
        except Exception as remap_ex:
            forms.alert('Could not rebuild optional parameter mapping before creation:\n{0}'.format(str(remap_ex)), title='Wall Library Builder')
            return

        selected_param_names = list(self.get_optional_mapping().keys())

        rename_affix_mode = 'Suffix'
        rename_affix_text = ' - Imported'
        try:
            rename_affix_mode = self.renameAffixModeCombo.SelectedItem.Content.ToString()
            rename_affix_text = self.renameAffixTextBox.Text
        except Exception:
            pass

        results = []
        errors = []
        param_messages = []
        warnings_total = 0
        created = 0
        updated = 0
        skipped = 0

        t = DB.Transaction(doc, 'Wall Library Builder - Create Wall Types')
        try:
            t.Start()
            for name in selected:
                try:
                    warnings_total += len(self.validation.get(name, {}).get('warnings', []))
                    status, created_name, msgs = create_or_update_wall_type(name, self.wall_data[name], template_wt, mode, selected_param_names, rename_affix_mode, rename_affix_text)
                    results.append('{0}: {1}'.format(status, created_name))
                    for msg in msgs:
                        param_messages.append('{0}: {1}'.format(created_name, msg))
                    if status.startswith('CREATED'):
                        created += 1
                    elif status == 'UPDATED':
                        updated += 1
                    elif status == 'SKIPPED':
                        skipped += 1
                except Exception as item_ex:
                    errors.append('{0}: {1}'.format(name, str(item_ex)))
            t.Commit()
        except Exception as ex:
            if t.HasStarted():
                t.RollBack()
            forms.alert(str(ex), title='Wall Library Builder - Transaction Error')
            return

        output.print_md('## Wall Library Builder Result Report')
        output.print_md('- Created: {0}'.format(created))
        output.print_md('- Updated: {0}'.format(updated))
        output.print_md('- Skipped: {0}'.format(skipped))
        output.print_md('- Warnings during preview: {0}'.format(warnings_total))
        output.print_md('- Optional parameter notes: {0}'.format(len(param_messages)))
        output.print_md('- Errors during creation: {0}'.format(len(errors)))
        output.print_md('### Details')
        for line in results:
            output.print_md('- {0}'.format(line))
        if param_messages:
            output.print_md('### Optional Parameter Notes')
            for m in param_messages:
                output.print_md('- {0}'.format(m))
        if errors:
            output.print_md('### Errors')
            for e in errors:
                output.print_md('- {0}'.format(e))

        self.statusText.Text = 'Done. Created {0}, updated {1}, skipped {2}, errors {3}.'.format(created, updated, skipped, len(errors))
        forms.alert('Done. Created {0}, updated {1}, skipped {2}. Errors: {3}.'.format(created, updated, skipped, len(errors)), title='Wall Library Builder')


def main():
    if not os.path.exists(XAML_FILE):
        forms.alert('XAML file not found:\n{0}'.format(XAML_FILE), title='Wall Library Builder')
        return

    win = WallLibraryBuilderWindow()
    win.ShowDialog()


if __name__ == '__main__':
    try:
        main()
    except Exception:
        output.print_md('## Wall Library Builder crashed')
        output.print_md('```')
        output.print_md(traceback.format_exc())
        output.print_md('```')
        forms.alert('Wall Library Builder crashed. Check pyRevit output panel for details.', title='Wall Library Builder')
