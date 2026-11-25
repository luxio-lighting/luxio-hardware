// Binary STL (millimetres) -> native SketchUp groups, using SketchUp's C SDK.
// Build on macOS:
// clang++ -std=c++17 -O2 export_sketchup.cpp -F "$SKETCHUP_SDK" \
//   -framework SketchUpAPI -Wl,-rpath,"$SKETCHUP_SDK" -o export_sketchup
// Run: export_sketchup manifest.tsv output.skp [geometry_scale=1000]
// Manifest: name<TAB>STL path<TAB>R,G,B<TAB>tx,ty,tz (translation in mm).
// Relative STL paths resolve against the manifest directory. # starts comments.
// Coordinates are converted to inches internally; model display units are mm.
// Enlarged definition geometry and inverse group scaling preserve tiny faces.
// Output groups are editable meshes; their dimensions in the model are 1:1.

#include <SketchUpAPI/sketchup.h>
#include <algorithm>
#include <array>
#include <cmath>
#include <cstdint>
#include <cstring>
#include <filesystem>
#include <fstream>
#include <iomanip>
#include <iostream>
#include <limits>
#include <map>
#include <set>
#include <sstream>
#include <stdexcept>
#include <string>
#include <vector>

#define CHECK(call) do { SUResult result = (call); if (result != SU_ERROR_NONE) \
  throw std::runtime_error(std::string(#call) + " failed (SUResult " + \
                           std::to_string(int(result)) + ")"); } while (false)

int main(int argc, char** argv) {
  if (argc < 3 || argc > 4) {
    std::cerr << "Usage: export_sketchup manifest.tsv output.skp [geometry_scale=1000]\n"
              << "TSV: name<TAB>STL path<TAB>R,G,B<TAB>tx,ty,tz\n";
    return 2;
  }
  SUModelRef model = SU_INVALID;
  bool initialized = false;
  try {
    const double geometry_scale = argc == 4 ? std::stod(argv[3]) : 1000.0;
    if (!std::isfinite(geometry_scale) || geometry_scale < 1.0)
      throw std::runtime_error("geometry_scale must be finite and at least 1");
    const auto manifest_path = std::filesystem::absolute(argv[1]);
    const auto output_path = std::filesystem::absolute(argv[2]);
    std::ifstream manifest(manifest_path);
    if (!manifest) throw std::runtime_error("Cannot read " + manifest_path.string());

    struct GroupRecord {
      std::string name;
      std::array<double, 3> low, high;
      size_t faces = 0, edges = 0;
    };
    std::map<std::string, GroupRecord> records;
    SUInitialize();
    initialized = true;
    CHECK(SUModelCreate(&model));
    CHECK(SUModelSetName(model, output_path.stem().string().c_str()));
    CHECK(SUModelSetDescription(model,
        "LX0002 enclosure mesh assembly. Millimetres, actual size. "
        "Separate named groups from the STL manifest. "
        "The PCB group is a fit reference, not a printable part."));
    SUEntitiesRef root = SU_INVALID;
    CHECK(SUModelGetEntities(model, &root));
    SUOptionsManagerRef options = SU_INVALID;
    SUOptionsProviderRef units = SU_INVALID;
    SUTypedValueRef value = SU_INVALID;
    CHECK(SUModelGetOptionsManager(model, &options));
    CHECK(SUOptionsManagerGetOptionsProviderByName(options, "UnitsOptions", &units));
    CHECK(SUTypedValueCreate(&value));
    CHECK(SUTypedValueSetInt32(value, 0));
    CHECK(SUOptionsProviderSetValue(units, "LengthFormat", value));
    CHECK(SUTypedValueSetInt32(value, 2));
    CHECK(SUOptionsProviderSetValue(units, "LengthUnit", value));
    CHECK(SUTypedValueSetInt32(value, 3));
    CHECK(SUOptionsProviderSetValue(units, "LengthPrecision", value));
    CHECK(SUTypedValueSetBool(value, false));
    CHECK(SUOptionsProviderSetValue(units, "LengthSnapEnabled", value));
    CHECK(SUTypedValueRelease(&value));

    std::string line;
    size_t line_number = 0;
    while (std::getline(manifest, line)) {
      ++line_number;
      if (!line.empty() && line.back() == '\r') line.pop_back();
      if (line.empty() || line[0] == '#') continue;
      std::vector<std::string> fields;
      std::istringstream row(line);
      std::string field;
      while (std::getline(row, field, '\t')) fields.push_back(field);
      if (fields.size() != 4 || fields[0].empty() || fields[1].empty())
        throw std::runtime_error("Manifest line " + std::to_string(line_number) +
                                 " needs four nonempty tab-separated fields");
      if (records.count(fields[0]))
        throw std::runtime_error("Duplicate group name: " + fields[0]);
      std::array<int, 3> rgb{};
      std::array<double, 3> translation{};
      std::replace(fields[2].begin(), fields[2].end(), ',', ' ');
      std::replace(fields[3].begin(), fields[3].end(), ',', ' ');
      std::istringstream colors(fields[2]), offset(fields[3]);
      if (!(colors >> rgb[0] >> rgb[1] >> rgb[2]) ||
          !(offset >> translation[0] >> translation[1] >> translation[2]))
        throw std::runtime_error("Invalid color/translation on manifest line " +
                                 std::to_string(line_number));
      for (size_t i = 0; i < 3; ++i)
        if (rgb[i] < 0 || rgb[i] > 255 || !std::isfinite(translation[i]))
          throw std::runtime_error("Color must be 0..255 and translation finite");
      auto stl_path = std::filesystem::path(fields[1]);
      if (stl_path.is_relative()) stl_path = manifest_path.parent_path() / stl_path;
      std::ifstream stl(stl_path, std::ios::binary | std::ios::ate);
      if (!stl) throw std::runtime_error("Cannot read " + stl_path.string());
      const auto byte_count = stl.tellg();
      stl.seekg(0);
      std::array<unsigned char, 84> header{};
      stl.read(reinterpret_cast<char*>(header.data()), header.size());
      const uint32_t triangle_count = uint32_t(header[80]) | (uint32_t(header[81]) << 8) |
          (uint32_t(header[82]) << 16) | (uint32_t(header[83]) << 24);
      if (!stl || triangle_count == 0 ||
          uint64_t(byte_count) != 84 + uint64_t(triangle_count) * 50)
        throw std::runtime_error("Expected complete binary STL: " + stl_path.string());

      constexpr double quantization_mm = 0.000001;
      std::map<std::array<int64_t, 3>, size_t> vertex_index;
      std::set<std::array<size_t, 3>> face_keys;
      std::vector<SUPoint3D> vertices;
      std::vector<std::array<size_t, 3>> triangles;
      vertices.reserve(triangle_count / 2);
      triangles.reserve(triangle_count);
      GroupRecord record;
      record.name = fields[0];
      record.low.fill(std::numeric_limits<double>::infinity());
      record.high.fill(-std::numeric_limits<double>::infinity());
      size_t degenerate = 0, duplicate = 0;
      double input_area = 0;
      for (uint32_t t = 0; t < triangle_count; ++t) {
        std::array<unsigned char, 50> bytes{};
        stl.read(reinterpret_cast<char*>(bytes.data()), bytes.size());
        std::array<size_t, 3> triangle{};
        for (size_t v = 0; v < 3; ++v) {
          std::array<int64_t, 3> key{};
          std::array<double, 3> point{};
          for (size_t axis = 0; axis < 3; ++axis) {
            const size_t b = 12 + (v * 3 + axis) * 4;
            const uint32_t bits = uint32_t(bytes[b]) | (uint32_t(bytes[b+1]) << 8) |
                (uint32_t(bytes[b+2]) << 16) | (uint32_t(bytes[b+3]) << 24);
            float coordinate;
            std::memcpy(&coordinate, &bits, sizeof(coordinate));
            if (!std::isfinite(coordinate) || std::abs(double(coordinate)) > 1000000.0)
              throw std::runtime_error("Invalid or excessive STL coordinate");
            point[axis] = coordinate;
            key[axis] = std::llround(point[axis] / quantization_mm);
            record.low[axis] = std::min(record.low[axis], point[axis] + translation[axis]);
            record.high[axis] = std::max(record.high[axis], point[axis] + translation[axis]);
          }
          auto inserted = vertex_index.emplace(key, vertices.size());
          triangle[v] = inserted.first->second;
          if (inserted.second)
            vertices.push_back({point[0] / 25.4 * geometry_scale,
                                point[1] / 25.4 * geometry_scale,
                                point[2] / 25.4 * geometry_scale});
        }
        const auto& a = vertices[triangle[0]];
        const auto& b = vertices[triangle[1]];
        const auto& c = vertices[triangle[2]];
        const double nx = (b.y-a.y)*(c.z-a.z) - (b.z-a.z)*(c.y-a.y);
        const double ny = (b.z-a.z)*(c.x-a.x) - (b.x-a.x)*(c.z-a.z);
        const double nz = (b.x-a.x)*(c.y-a.y) - (b.y-a.y)*(c.x-a.x);
        if (triangle[0] == triangle[1] || triangle[1] == triangle[2] ||
            triangle[0] == triangle[2] || nx*nx + ny*ny + nz*nz < 1e-24) {
          ++degenerate;
          continue;
        }
        auto face_key = triangle;
        std::sort(face_key.begin(), face_key.end());
        if (!face_keys.insert(face_key).second) { ++duplicate; continue; }
        input_area += .5 * std::sqrt(nx*nx + ny*ny + nz*nz);
        triangles.push_back(triangle);
      }
      if (!stl || triangles.empty()) throw std::runtime_error("Empty or truncated STL mesh");

      SUGroupRef group = SU_INVALID;
      CHECK(SUGroupCreate(&group));
      CHECK(SUGroupSetName(group, record.name.c_str()));
      CHECK(SUEntitiesAddGroup(root, group));
      SUTransformation transform{};
      transform.values[0] = transform.values[5] = transform.values[10] = 1.0 / geometry_scale;
      transform.values[15] = 1.0;
      transform.values[12] = translation[0] / 25.4;
      transform.values[13] = translation[1] / 25.4;
      transform.values[14] = translation[2] / 25.4;
      CHECK(SUGroupSetTransform(group, &transform));
      SUEntitiesRef entities = SU_INVALID;
      CHECK(SUGroupGetEntities(group, &entities));
      SUGeometryInputRef geometry = SU_INVALID;
      CHECK(SUGeometryInputCreate(&geometry));
      CHECK(SUGeometryInputSetVertices(geometry, vertices.size(), vertices.data()));
      for (const auto& triangle : triangles) {
        SULoopInputRef loop = SU_INVALID;
        CHECK(SULoopInputCreate(&loop));
        for (size_t index : triangle) CHECK(SULoopInputAddVertexIndex(loop, index));
        size_t face_index = 0;
        CHECK(SUGeometryInputAddFace(geometry, &loop, &face_index));
      }
      // Vertices are already deduplicated, so do not let the SDK weld close details.
      CHECK(SUEntitiesFill(entities, geometry, false));
      CHECK(SUGeometryInputRelease(&geometry));
      CHECK(SUEntitiesGetNumFaces(entities, &record.faces));
      CHECK(SUEntitiesGetNumEdges(entities, false, &record.edges));
      if (record.faces != triangles.size()) {
        // The combined PCB visualization includes overlapping supplier solids
        // and sub-micron STL slivers. Preserve strict equality for printable
        // case geometry; permit only negligible reference-only SDK merging.
        std::vector<SUFaceRef> reference_faces(record.faces);
        size_t face_count = 0;
        CHECK(SUEntitiesGetFaces(entities, reference_faces.size(), reference_faces.data(), &face_count));
        double output_area = 0;
        for (auto face : reference_faces) {
          double area = 0;
          CHECK(SUFaceGetArea(face, &area));
          output_area += area;
        }
        const double area_difference_mm2 = std::abs(input_area - output_area) *
            25.4 * 25.4 / (geometry_scale * geometry_scale);
        if (record.name != "PCB reference" || record.faces > triangles.size() ||
            triangles.size() - record.faces > 100 || area_difference_mm2 > .01)
          throw std::runtime_error(record.name + ": face count changed during fill (" +
              std::to_string(triangles.size()) + " -> " + std::to_string(record.faces) +
              "); surface area difference " + std::to_string(area_difference_mm2) + "mm2");
        std::cout << record.name << ": " << triangles.size() - record.faces
                  << " reference-only facets merged by SDK; surface area difference "
                  << std::setprecision(12) << area_difference_mm2 << "mm2\n";
      }

      SUMaterialRef material = SU_INVALID;
      CHECK(SUMaterialCreate(&material));
      CHECK(SUMaterialSetName(material, (record.name + " color").c_str()));
      const SUColor color = {uint8_t(rgb[0]), uint8_t(rgb[1]), uint8_t(rgb[2]), 255};
      CHECK(SUMaterialSetColor(material, &color));
      CHECK(SUModelAddMaterials(model, 1, &material));
      CHECK(SUDrawingElementSetMaterial(SUGroupToDrawingElement(group), material));
      std::vector<SUEdgeRef> edges(record.edges);
      size_t returned = 0, hidden_edges = 0, boundary_edges = 0, nonmanifold_edges = 0;
      CHECK(SUEntitiesGetEdges(entities, false, edges.size(), edges.data(), &returned));
      for (auto edge : edges) {
        size_t face_count = 0;
        CHECK(SUEdgeGetNumFaces(edge, &face_count));
        if (face_count == 1) ++boundary_edges;
        if (face_count > 2) ++nonmanifold_edges;
        if (face_count != 2) continue;
        SUFaceRef faces[2];
        CHECK(SUEdgeGetFaces(edge, 2, faces, &returned));
        SUVector3D a{}, b{};
        CHECK(SUFaceGetNormal(faces[0], &a));
        CHECK(SUFaceGetNormal(faces[1], &b));
        if (a.x*b.x + a.y*b.y + a.z*b.z > 0.9999999) {
          CHECK(SUEdgeSetSoft(edge, true));
          CHECK(SUEdgeSetSmooth(edge, true));
          CHECK(SUDrawingElementSetHidden(SUEdgeToDrawingElement(edge), true));
          ++hidden_edges;
        }
      }
      std::cout << record.name << ": " << triangle_count << " STL triangles, "
                << vertices.size() << " shared vertices, " << record.faces << " faces, "
                << record.edges << " edges, " << hidden_edges << " coplanar edges hidden; "
                << degenerate << " degenerate / " << duplicate << " duplicate triangles removed; "
                << boundary_edges << " boundary / " << nonmanifold_edges << " nonmanifold edges\n";
      records.emplace(record.name, record);
    }
    if (records.empty()) throw std::runtime_error("Manifest contains no groups");

    SUBoundingBox3D model_bounds{};
    CHECK(SUEntitiesGetBoundingBox(root, &model_bounds));
    const SUPoint3D center = {(model_bounds.min_point.x + model_bounds.max_point.x)/2,
                             (model_bounds.min_point.y + model_bounds.max_point.y)/2,
                             (model_bounds.min_point.z + model_bounds.max_point.z)/2};
    const double span = std::max({model_bounds.max_point.x-model_bounds.min_point.x,
                                 model_bounds.max_point.y-model_bounds.min_point.y,
                                 model_bounds.max_point.z-model_bounds.min_point.z});
    const SUPoint3D eye = {center.x-span, center.y-span, center.z+span};
    const SUVector3D up = {0, 0, 1};
    SUCameraRef camera = SU_INVALID;
    CHECK(SUCameraCreate(&camera));
    CHECK(SUCameraSetOrientation(camera, &eye, &center, &up));
    CHECK(SUCameraSetPerspective(camera, false));
    CHECK(SUCameraSetAspectRatio(camera, 1.6));
    CHECK(SUCameraSetOrthographicFrustumHeight(camera, span*1.3));
    CHECK(SUModelSetCamera(model, &camera));
    CHECK(SUModelSaveToFile(model, output_path.string().c_str()));
    CHECK(SUModelRelease(&model));

    SUModelLoadStatus load_status;
    CHECK(SUModelCreateFromFileWithStatus(&model, output_path.string().c_str(), &load_status));
    CHECK(SUModelGetEntities(model, &root));
    SUModelUnits read_units;
    CHECK(SUModelGetUnits(model, &read_units));
    if (read_units != SUModelUnits_Millimeters) throw std::runtime_error("Reloaded units are not mm");
    size_t group_count = 0, returned = 0;
    CHECK(SUEntitiesGetNumGroups(root, &group_count));
    if (group_count != records.size()) throw std::runtime_error("Reloaded group count differs");
    std::vector<SUGroupRef> groups(group_count);
    CHECK(SUEntitiesGetGroups(root, groups.size(), groups.data(), &returned));
    for (auto group : groups) {
      SUStringRef name_ref = SU_INVALID;
      CHECK(SUStringCreate(&name_ref));
      CHECK(SUGroupGetName(group, &name_ref));
      size_t length = 0;
      CHECK(SUStringGetUTF8Length(name_ref, &length));
      std::vector<char> buffer(length + 1);
      CHECK(SUStringGetUTF8(name_ref, buffer.size(), buffer.data(), &returned));
      CHECK(SUStringRelease(&name_ref));
      const std::string name(buffer.data());
      if (!records.count(name)) throw std::runtime_error("Unknown reloaded group name: " + name);
      const auto& record = records.at(name);
      SUEntitiesRef entities = SU_INVALID;
      CHECK(SUGroupGetEntities(group, &entities));
      size_t faces = 0, edges = 0;
      CHECK(SUEntitiesGetNumFaces(entities, &faces));
      CHECK(SUEntitiesGetNumEdges(entities, false, &edges));
      if (faces != record.faces || edges != record.edges)
        throw std::runtime_error(name + ": geometry count changed when reloaded");
      SUBoundingBox3D bounds{};
      CHECK(SUDrawingElementGetBoundingBox(SUGroupToDrawingElement(group), &bounds));
      const std::array<double, 3> low = {bounds.min_point.x*25.4,
                                       bounds.min_point.y*25.4, bounds.min_point.z*25.4};
      const std::array<double, 3> high = {bounds.max_point.x*25.4,
                                        bounds.max_point.y*25.4, bounds.max_point.z*25.4};
      for (size_t axis = 0; axis < 3; ++axis)
        if (std::abs(low[axis]-record.low[axis]) > 0.0001 ||
            std::abs(high[axis]-record.high[axis]) > 0.0001)
          throw std::runtime_error(name + ": reloaded bounding box differs from STL + translation");
      std::cout << std::fixed << std::setprecision(4) << "Verified " << name
                << " bounds mm: [" << low[0] << ", " << low[1] << ", " << low[2]
                << "] .. [" << high[0] << ", " << high[1] << ", " << high[2] << "]\n";
    }
    CHECK(SUModelRelease(&model));
    SUTerminate();
    initialized = false;
    std::cout << "PASS: saved and reopened " << output_path << "; " << group_count
              << " named groups, unchanged face/edge counts and bounds, millimetre units.\n";
    return 0;
  } catch (const std::exception& error) {
    std::cerr << "ERROR: " << error.what() << '\n';
    if (SUIsValid(model)) SUModelRelease(&model);
    if (initialized) SUTerminate();
    return 1;
  }
}
