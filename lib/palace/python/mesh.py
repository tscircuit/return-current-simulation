"""Generate a conforming 3D Gmsh mesh. All dimensions are millimetres.
No field solver is implemented here: Palace solves the driven Maxwell system.
"""

import argparse
import json
from pathlib import Path

import gmsh
from shapely.geometry import LineString, Polygon
from shapely.ops import unary_union


def points(outline):
    return [(p["x"], p["y"]) for p in outline]


def add_ring(coordinates, z):
    vertices = [gmsh.model.occ.addPoint(x, y, z) for x, y in list(coordinates)[:-1]]
    edges = [
        gmsh.model.occ.addLine(vertices[i], vertices[(i + 1) % len(vertices)])
        for i in range(len(vertices))
    ]
    return gmsh.model.occ.addCurveLoop(edges)


def add_polygon(polygon, z):
    rings = [add_ring(polygon.exterior.coords, z)]
    rings.extend(add_ring(ring.coords, z) for ring in polygon.interiors)
    return (2, gmsh.model.occ.addPlaneSurface(rings))


def polygons(shape):
    if shape.geom_type == "Polygon":
        return [shape]
    if shape.geom_type == "MultiPolygon":
        return list(shape.geoms)
    raise ValueError("Expected nonempty copper polygons")


def add_port(port, model):
    endpoint, neighbor = port
    x, y = endpoint["x"], endpoint["y"]
    dx, dy = neighbor["x"] - x, neighbor["y"] - y
    length = (dx * dx + dy * dy) ** 0.5
    half_width = model["portWidth"] / 2
    tx, ty = -dy / length * half_width, dx / length * half_width
    corners = [
        (x - tx, y - ty, 0),
        (x + tx, y + ty, 0),
        (x + tx, y + ty, model["layerSeparation"]),
        (x - tx, y - ty, model["layerSeparation"]),
    ]
    vertices = [gmsh.model.occ.addPoint(*corner) for corner in corners]
    edges = [
        gmsh.model.occ.addLine(vertices[i], vertices[(i + 1) % 4]) for i in range(4)
    ]
    return (2, gmsh.model.occ.addPlaneSurface([gmsh.model.occ.addCurveLoop(edges)]))


def generate_mesh(model, destination):
    geometry = model["geometry"]
    board = Polygon(points(geometry["boardOutline"]))
    for cutout in geometry["cutouts"]:
        board = board.difference(Polygon(points(cutout)))
    ground = unary_union(
        [
            Polygon(points(region["outer"]), [points(hole) for hole in region["holes"]])
            for region in geometry["groundRegions"]
        ]
    ).intersection(board)
    if not board.is_valid or not ground.is_valid:
        raise ValueError("Invalid PCB/ground polygon")
    pads = [Polygon(points(outline)) for outline in model["topPads"]]
    signals = []
    ports = []
    for signal in geometry["signals"]:
        route = [
            point
            for index, point in enumerate(signal["route"])
            if index == 0
            or (point["x"], point["y"])
            != (signal["route"][index - 1]["x"], signal["route"][index - 1]["y"])
        ]
        strips = [
            LineString([(start["x"], start["y"]), (end["x"], end["y"])]).buffer(
                start["width"] / 2, cap_style="square", join_style="mitre"
            )
            for start, end in zip(route, route[1:])
        ]
        trace = unary_union(strips)
        connected_pads = [pad for pad in pads if pad.intersects(trace)]
        trace = unary_union([trace, *connected_pads])
        if not board.covers(trace):
            raise ValueError("Signal copper leaves the substrate")
        for other in signals:
            if other.intersects(trace):
                raise ValueError("Top signal copper overlaps another signal")
        signals.append(trace)
        ports.extend([(route[0], route[1]), (route[-1], route[-2])])
    for endpoint, neighbor in ports:
        dx, dy = neighbor["x"] - endpoint["x"], neighbor["y"] - endpoint["y"]
        length = (dx * dx + dy * dy) ** 0.5
        tx, ty = (
            -dy / length * model["portWidth"] / 2,
            dx / length * model["portWidth"] / 2,
        )
        contact = LineString(
            [
                (endpoint["x"] - tx, endpoint["y"] - ty),
                (endpoint["x"] + tx, endpoint["y"] + ty),
            ]
        )
        if not ground.covers(contact):
            raise ValueError("Port aperture leaves ground copper")
        if not unary_union(signals).covers(contact):
            raise ValueError("Port aperture leaves signal copper")
    if any(not any(pad.intersects(signal) for signal in signals) for pad in pads):
        raise ValueError(
            "Unconnected top SMT pads are not supported by this reference model"
        )
    gmsh.initialize()
    try:
        gmsh.model.add("return-current")
        height = model["layerSeparation"]
        substrate_surfaces = [add_polygon(polygon, 0) for polygon in polygons(board)]
        substrate = [
            entity
            for surface in substrate_surfaces
            for entity in gmsh.model.occ.extrude([surface], 0, 0, height)
            if entity[0] == 3
        ]
        min_x, min_y, max_x, max_y = board.bounds
        padding = model["airPadding"]
        air = (
            3,
            gmsh.model.occ.addBox(
                min_x - padding,
                min_y - padding,
                -padding,
                max_x - min_x + 2 * padding,
                max_y - min_y + 2 * padding,
                height + 2 * padding,
            ),
        )
        ground_surfaces = [add_polygon(polygon, 0) for polygon in polygons(ground)]
        signal_surfaces = [
            add_polygon(polygon, height)
            for signal in signals
            for polygon in polygons(signal)
        ]
        copper = [
            entity
            for surface in ground_surfaces
            for entity in gmsh.model.occ.extrude(
                [surface], 0, 0, -model["copperThickness"]
            )
            if entity[0] == 3
        ]
        copper += [
            entity
            for surface in signal_surfaces
            for entity in gmsh.model.occ.extrude(
                [surface], 0, 0, model["copperThickness"]
            )
            if entity[0] == 3
        ]
        port_surfaces = [add_port(port, model) for port in ports]
        tools = [
            *substrate,
            *copper,
            *ground_surfaces,
            *signal_surfaces,
            *port_surfaces,
        ]
        _, mapping = gmsh.model.occ.fragment([air], tools)
        gmsh.model.occ.synchronize()
        substrate_tags = {
            tag
            for descendants in mapping[1 : 1 + len(substrate)]
            for dim, tag in descendants
            if dim == 3
        }
        copper_tags = {
            tag
            for descendants in mapping[
                1 + len(substrate) : 1 + len(substrate) + len(copper)
            ]
            for dim, tag in descendants
            if dim == 3
        }
        air_tags = (
            {tag for dim, tag in mapping[0] if dim == 3} - substrate_tags - copper_tags
        )
        gmsh.model.addPhysicalGroup(3, sorted(copper_tags), 3, "copper")
        gmsh.model.addPhysicalGroup(3, sorted(air_tags), 1, "air")
        gmsh.model.addPhysicalGroup(3, sorted(substrate_tags), 2, "substrate")
        offset = 1 + len(substrate) + len(copper)
        ground_tags = sorted(
            {
                tag
                for descendants in mapping[offset : offset + len(ground_surfaces)]
                for dim, tag in descendants
                if dim == 2
            }
        )
        offset += len(ground_surfaces)
        signal_tags = sorted(
            {
                tag
                for descendants in mapping[offset : offset + len(signal_surfaces)]
                for dim, tag in descendants
                if dim == 2
            }
        )
        offset += len(signal_surfaces)
        gmsh.model.addPhysicalGroup(2, ground_tags, 11, "ground")
        gmsh.model.addPhysicalGroup(2, signal_tags, 12, "signals")
        port_tags = []
        for index, descendants in enumerate(mapping[offset:]):
            tags = [tag for dim, tag in descendants if dim == 2]
            gmsh.model.addPhysicalGroup(2, tags, 21 + index, f"port-{index + 1}")
            port_tags.extend(tags)
        outer = [
            tag
            for dim, tag in gmsh.model.getBoundary(
                [(3, tag) for tag in sorted(air_tags | substrate_tags | copper_tags)],
                combined=True,
                oriented=False,
            )
            if dim == 2
        ]
        gmsh.model.addPhysicalGroup(2, outer, 13, "outer-air")
        copper_edges = sorted(
            {
                tag
                for dim, tag in gmsh.model.getBoundary(
                    [(2, tag) for tag in [*ground_tags, *signal_tags, *port_tags]],
                    combined=False,
                    oriented=False,
                )
                if dim == 1
            }
        )
        distance = gmsh.model.mesh.field.add("Distance")
        gmsh.model.mesh.field.setNumbers(distance, "CurvesList", copper_edges)
        gmsh.model.mesh.field.setNumber(distance, "Sampling", 100)
        threshold = gmsh.model.mesh.field.add("Threshold")
        gmsh.model.mesh.field.setNumber(threshold, "InField", distance)
        gmsh.model.mesh.field.setNumber(
            threshold, "SizeMin", min(model["meshSize"] / 3, model["portWidth"] / 2)
        )
        gmsh.model.mesh.field.setNumber(threshold, "SizeMax", model["meshSize"])
        gmsh.model.mesh.field.setNumber(threshold, "DistMin", 0.05)
        gmsh.model.mesh.field.setNumber(threshold, "DistMax", 1.5)
        gmsh.model.mesh.field.setAsBackgroundMesh(threshold)
        gmsh.option.setNumber("Mesh.MeshSizeExtendFromBoundary", 0)
        gmsh.option.setNumber("Mesh.MeshSizeFromPoints", 0)
        gmsh.option.setNumber("Mesh.MeshSizeFromCurvature", 0)
        gmsh.option.setNumber("Mesh.Algorithm3D", 10)
        gmsh.option.setNumber("General.NumThreads", 4)
        gmsh.option.setNumber("Mesh.MshFileVersion", 2.2)
        gmsh.model.mesh.generate(3)
        gmsh.write(str(destination / "mesh.msh"))
        summary = {
            "nodes": len(gmsh.model.mesh.getNodes()[0]),
            "tetrahedra": sum(len(tags) for tags in gmsh.model.mesh.getElements(3)[1]),
            "groundAttribute": 11,
            "signalAttribute": 12,
            "portAttributes": list(range(21, 21 + len(ports))),
        }
        (destination / "mesh-summary.json").write_text(
            json.dumps(summary, indent=2) + "\n"
        )
    finally:
        gmsh.finalize()
    return len(ports)


def create_configuration(model, port_count):
    ports = [
        {
            "Index": index + 1,
            "Attributes": [21 + index],
            "Direction": "-Z",
            "R": model["portResistance"],
            **({"Excitation": index + 1} if index % 2 == 0 else {}),
        }
        for index in range(port_count)
    ]
    return {
        "Problem": {"Type": "Driven", "Verbose": 2, "Output": "postpro"},
        "Model": {
            "Mesh": "mesh.msh",
            "L0": 1e-3,
            "Lc": 1.0,
            "CrackInternalBoundaryElements": False,
        },
        "Domains": {
            "Materials": [
                {"Attributes": [1], "Permittivity": 1.0, "Permeability": 1.0},
                {
                    "Attributes": [2],
                    "Permittivity": model["substratePermittivity"],
                    "Permeability": 1.0,
                    "LossTan": model["substrateLossTangent"],
                },
                {
                    "Attributes": [3],
                    "Permittivity": 1.0,
                    "Permeability": 1.0,
                    "Conductivity": model["copperConductivity"],
                },
            ]
        },
        "Boundaries": {
            "Absorbing": {"Attributes": [13], "Order": 1},
            "LumpedPort": ports,
        },
        "Solver": {
            "Order": model["order"],
            "Device": "CPU",
            "Driven": {
                "Samples": [
                    {
                        "Type": "Point",
                        "Freq": [model["frequencyHz"] / 1e9],
                        "SaveStep": 1,
                    }
                ]
            },
            "Linear": {
                "Type": "SuperLU",
                "KSPType": "GMRES",
                "Tol": 1e-9,
                "MaxIts": 200,
                "ComplexCoarseSolve": True,
                "PCMatShifted": False,
            },
        },
    }


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("model")
    args = parser.parse_args()
    source = Path(args.model).resolve()
    model = json.loads(source.read_text())
    count = generate_mesh(model, source.parent)
    (source.parent / "palace.json").write_text(
        json.dumps(create_configuration(model, count), indent=2) + "\n"
    )


if __name__ == "__main__":
    main()
