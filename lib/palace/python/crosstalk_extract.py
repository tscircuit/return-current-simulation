"""Conservative 2D electrostatic extraction of uniform microstrip C and external L.

All lengths are meters internally. Link conductance is epsilon*face_length/distance
(F/m in a 2D cross-section), and conductor charge is the outward flux sum.
The identical vacuum problem gives L*C_vacuum=I/c0**2 for external TEM fields.
This is an educational quasi-static model, not a validated production EM solver.
"""
import json
import math
import time
from pathlib import Path

import numpy as np
from scipy.sparse import coo_matrix
from scipy.sparse.linalg import splu

EPS0 = 8.8541878128e-12
C0 = 299792458.0
ROOT = Path(__file__).resolve().parent


def mesh_axis(breaks, fine, fine_region):
    """Exact boundaries, fine near metal, bounded coarsening in distant regions."""
    result = []
    for a, b in zip(breaks[:-1], breaks[1:]):
        middle = (a+b)/2
        distance = max(fine_region[0]-middle, middle-fine_region[1], 0)
        step = min(fine*max(1, distance/0.0004), 0.00025)
        n = max(1, math.ceil((b-a)/step))
        result.extend(np.linspace(a, b, n+1)[:-1])
    return np.array(result + [breaks[-1]])


def electrostatic(x, y, labels, height, er):
    """Return Maxwell capacitance matrix from fixed electrode voltage solves."""
    ny, nx = labels.shape
    ids = np.arange(nx*ny).reshape(ny, nx)
    dx, dy = np.diff(x), np.diff(y)
    face_x = np.r_[dx[0]/2, (dx[:-1]+dx[1:])/2, dx[-1]/2]
    face_y = np.r_[dy[0]/2, (dy[:-1]+dy[1:])/2, dy[-1]/2]
    # Dielectric interface is an exact grid line. Horizontal dual faces can
    # straddle it: integrate epsilon over that face (parallel flux paths).
    y_lo = np.r_[y[0], (y[:-1]+y[1:])/2]
    y_hi = np.r_[(y[:-1]+y[1:])/2, y[-1]]
    below = np.maximum(0, np.minimum(y_hi, height)-y_lo)
    horizontal_eps_face = EPS0*(face_y+(er-1)*below)
    # Vertical links do not cross the aligned interface: one epsilon each.
    vertical_eps = EPS0*np.where((y[:-1]+y[1:])/2 < height, er, 1)
    a = np.r_[ids[:, :-1].ravel(), ids[:-1, :].ravel()]
    b = np.r_[ids[:, 1:].ravel(), ids[1:, :].ravel()]
    g = np.r_[(horizontal_eps_face[:, None]/dx).ravel(),
              (vertical_eps[:, None]*face_x[None, :]/dy[:, None]).ravel()]
    matrix = coo_matrix((np.r_[g,g,-g,-g],
                        (np.r_[a,b,a,b], np.r_[a,b,b,a])),
                       shape=(nx*ny, nx*ny)).tocsc()
    flat = labels.ravel()
    unknown = np.flatnonzero(flat < 0)
    fixed = np.flatnonzero(flat >= 0)
    count = int(flat.max())
    fixed_v = np.column_stack([(flat[fixed] == j).astype(float)
                               for j in range(1,count+1)])
    operator = matrix[unknown][:, unknown]
    rhs = -matrix[unknown][:, fixed]@fixed_v
    factor = splu(operator)
    phi = np.zeros((nx*ny,count))
    phi[fixed] = fixed_v
    phi[unknown] = factor.solve(rhs)
    residual = np.max(np.abs(operator@phi[unknown]-rhs))/np.max(np.abs(rhs))
    charges = matrix@phi
    cap = np.array([charges[flat == j].sum(axis=0) for j in range(1,count+1)])
    reciprocity = np.max(np.abs(cap-cap.T))/np.max(np.abs(cap))
    if residual > 1e-9 or reciprocity > 1e-9:
        raise ValueError('Electrostatic conservation/reciprocity failure')
    return cap, {'nodes': nx*ny, 'unknowns': len(unknown),
                 'relative_residual': float(residual),
                 'relative_reciprocity_error': float(reciprocity)}, phi


def cross_section(geom, gap_mm, fine_mm, margin_mm=4, top_mm=4):
    w, t, h = [geom[k]*1e-3 for k in
               ('trace_width_mm','trace_thickness_mm','substrate_height_mm')]
    s = gap_mm*1e-3
    rects = [(-s/2-w, -s/2), (s/2,s/2+w)]
    fine = fine_mm*1e-3
    xedge = s/2+w
    # Include progressively farther edges to keep the same near-field mesh
    # in a domain-size check, so boundary error is not conflated with grid error.
    xbreaks = sorted(set([-xedge-margin_mm*1e-3, -xedge-.002, -xedge-.001,
                         -xedge-.0004, *[v for r in rects for v in r],
                         xedge+.0004,xedge+.001,xedge+.002,xedge+margin_mm*1e-3]))
    ybreaks = sorted(set([0, h, h+t, h+t+.0004, .001, .002, top_mm*1e-3]))
    x = mesh_axis(xbreaks,fine,(-xedge-.0004,xedge+.0004))
    y = mesh_axis(ybreaks,fine,(0,h+t+.0004))
    X,Y = np.meshgrid(x,y)
    labels = np.full(X.shape,-1)
    labels[0,:] = 0
    for j,(left,right) in enumerate(rects,1):
        labels[(X >= left-1e-15)&(X <= right+1e-15)&
               (Y >= h-1e-15)&(Y <= h+t+1e-15)] = j
    return x,y,labels


def extract(assumptions, gap_mm, fine_mm, margin_mm=4, top_mm=4):
    x,y,labels = cross_section(assumptions['geometry'],gap_mm,fine_mm,margin_mm,top_mm)
    if len(x)*len(y) > 200000:
        raise ValueError('Cross-section exceeds the 200000-node resource budget')
    h = assumptions['geometry']['substrate_height_mm']*1e-3
    er = assumptions['materials']['relative_permittivity']
    cap,stats,phi = electrostatic(x,y,labels,h,er)
    vacuum,stats0,_ = electrostatic(x,y,labels,h,1)
    inductance = np.linalg.inv(vacuum)/C0**2
    geom,mat = assumptions['geometry'],assumptions['materials']
    resistance = 1/(mat['trace_conductivity_s_per_m'] *
                    geom['trace_width_mm']*1e-3 * geom['trace_thickness_mm']*1e-3)
    values = {'gap_mm':gap_mm, 'grid_mm':fine_mm, 'margin_mm':margin_mm,'top_mm':top_mm,
              'C_f_per_m':cap.tolist(), 'C_vacuum_f_per_m':vacuum.tolist(),
              'L_h_per_m':inductance.tolist(), 'R_ohm_per_m':(np.eye(2)*resistance).tolist(),
              'G_s_per_m':np.zeros((2,2)).tolist(), 'electrostatic':stats,'vacuum':stats0}
    values['eigenvalues'] = {name:np.linalg.eigvalsh(np.array(values[name])).tolist()
                             for name in ('C_f_per_m','C_vacuum_f_per_m','L_h_per_m','R_ohm_per_m','G_s_per_m')}
    values['electric_coupling_coefficient'] = float(-cap[0,1]/np.sqrt(cap[0,0]*cap[1,1]))
    values['magnetic_coupling_coefficient'] = float(inductance[0,1]/np.sqrt(inductance[0,0]*inductance[1,1]))
    if np.min(np.linalg.eigvalsh(cap)) <= 0 or np.min(np.linalg.eigvalsh(inductance)) <= 0:
        raise ValueError('Non-passive extracted LC')
    if np.any(cap.sum(axis=1)<=0) or cap[0,1] >= 0:
        raise ValueError('Invalid Maxwell capacitance signs')
    return values, (x,y,labels,phi)

