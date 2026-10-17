"""Editable starting values: E/G kN/m²; rho weight density kN/m³."""
PRESETS = {
    'Steel': {'E':200000000., 'G':76923076.923, 'nu':0.3, 'rho':76.98},
    'Concrete': {'E':33000000., 'G':13750000., 'nu':0.2, 'rho':25.},
    'Aluminium': {'E':70000000., 'G':70000000./2.6, 'nu':0.3, 'rho':2700.*9.80665/1000.},
    'Wood': {'E':11000000., 'G':690000., 'nu':0.42, 'rho':420.*9.80665/1000.},
}
NOTES = {
    'Steel':'Steel: editable reference values; E = 200 GPa.',
    'Concrete':'Concrete: C30/37 starting values, uncracked E = 33 GPa; rho = 25 kN/m³. Edit for grade/cracking.',
    'Aluminium':'Aluminium: generic starting values, E = 70 GPa; mass density 2700 kg/m³ converted to weight density.',
    'Wood':'Wood: C24-like longitudinal E = 11 GPa, G = 0.69 GPa. Member axis follows grain; scalar model, not full orthotropic timber analysis.',
}

def material_preset(name):
    return dict(id=name, **PRESETS[name])
