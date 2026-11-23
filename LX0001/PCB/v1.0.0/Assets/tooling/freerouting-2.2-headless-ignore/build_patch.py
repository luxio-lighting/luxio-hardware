"""Build a minimal, auditable local fix for FreeRouting 2.2 headless -inc."""
from pathlib import Path
import hashlib
import subprocess
import sys
import tempfile
import zipfile

root = Path(__file__).resolve().parent
if len(sys.argv) != 4:
    raise SystemExit("Usage: python3 build_patch.py ORIGINAL_JAR JAVAC_25 OUTPUT_JAR")
original, javac, output = map(Path, sys.argv[1:])
if original.resolve() == output.resolve():
    raise SystemExit("The original JAR must remain unchanged")
original_hash = hashlib.sha256(original.read_bytes()).hexdigest()
assert original_hash == "c5642db8dbf00cf906a00e1c2099acc957a82346704e1bf6083e549383afdb27", original_hash
source_path = root / "RoutingJobSchedulerActionThread.upstream.java"
source_bytes = source_path.read_bytes()
source_hash = hashlib.sha256(source_bytes).hexdigest()
assert source_hash == "45b80a9b245fb5ed72a29fcf22460b038d0ad880f28ba56c31ffe4975c358137", source_hash
source = source_bytes.decode()
needle = "  protected void thread_action() {\n"
assert source.count(needle) == 1
patch = '''    // LX0001 local fix: GuiManager applies this flag, but headless jobs do not.
    // DSN plane imports default to non-obstacles. The optional capsule-areas
    // exporter represents existing real copper, so other nets must avoid it.
    if (Boolean.getBoolean("lx0001.areaObstacles")) {
      job.board.rules.set_ignore_conduction(true);
      job.board.change_conduction_is_obstacle(true);
      job.logInfo("LX0001 experiment: imported conduction areas are obstacles.");
      // These are finite copper capsules, not continuous supply planes.
      // Plane-mode routing otherwise returns CONNECTED_TO_PLANE for an
      // island touching any capsule and never joins disconnected islands.
      int finiteCopperNets = 0;
      for (int netNo = 1; netNo <= job.board.rules.nets.max_net_no(); netNo++) {
        var routeNet = job.board.rules.nets.get(netNo);
        if (routeNet != null && routeNet.contains_plane()) {
          routeNet.set_contains_plane(false);
          finiteCopperNets++;
        }
      }
      job.logInfo("LX0001 experiment: treating " + finiteCopperNets + " area nets as finite copper.");
    }
    // CliSettings 2.2 also omits -inc, so fall back to the legacy CLI parser.
    String[] ignoredNetClasses = job.routerSettings.ignoreNetClasses;
    if (ignoredNetClasses == null || ignoredNetClasses.length == 0) {
      ignoredNetClasses = Freerouting.globalSettings.routerSettings.ignoreNetClasses;
    }
    if (ignoredNetClasses != null) {
      for (String ignoredName : ignoredNetClasses) {
        String requestedName = ignoredName.trim();
        boolean matched = false;
        for (int i = 0; i < job.board.rules.net_classes.count(); i++) {
          var netClass = job.board.rules.net_classes.get(i);
          if (netClass.get_name().equalsIgnoreCase(requestedName)) {
            netClass.is_ignored_by_autorouter = true;
            matched = true;
            job.logInfo("LX0001 headless fix: ignoring net class '" + netClass.get_name() + "'.");
          }
        }
        if (!matched) {
          job.logWarning("LX0001 headless fix: requested ignored class not found: " + requestedName);
        }
      }
    }
'''
source = source.replace(needle, needle + patch)
with tempfile.TemporaryDirectory(prefix="lx0001-router-patch-") as temporary:
    work = Path(temporary)
    java = work / "RoutingJobSchedulerActionThread.java"
    java.write_text(source)
    batch_bytes = (root / "BatchAutorouter.upstream.java").read_bytes()
    assert hashlib.sha256(batch_bytes).hexdigest() == "22a1adeb33c29c5ed10421a83aff735692fd02fd7010c7e5e395a4d1786b8c84"
    batch_source = batch_bytes.decode()
    old_cleanup = '''    board.start_marking_changed_area();
    board.remove_trace_tails(-1, p_stop_connection_option);
    board.opt_changed_area(new int[0], null, this.trace_pull_tight_accuracy, this.trace_cost_arr, this.thread,
        TIME_LIMIT_TO_PREVENT_ENDLESS_LOOP);'''
    new_cleanup = '''    // LX0001: cleanup must honor the same ignored classes as route selection.
    // A positive net number also prevents combine_traces from touching other nets.
    for (int netNo = 1; netNo <= board.rules.nets.max_net_no(); netNo++) {
      Net net = board.rules.nets.get(netNo);
      if (net == null || net.get_class().is_ignored_by_autorouter) {
        continue;
      }
      board.start_marking_changed_area();
      board.remove_trace_tails(netNo, p_stop_connection_option);
      if (!Boolean.getBoolean("lx0001.skipCleanupPullTight")) {
        board.opt_changed_area(new int[] { netNo }, null, this.trace_pull_tight_accuracy,
            this.trace_cost_arr, this.thread, TIME_LIMIT_TO_PREVENT_ENDLESS_LOOP);
      }
    }'''
    assert batch_source.count(old_cleanup) == 1
    batch = work / "BatchAutorouter.java"
    batch.write_text(batch_source.replace(old_cleanup, new_cleanup))
    trace_bytes = (root / "PolylineTrace.upstream.java").read_bytes()
    assert hashlib.sha256(trace_bytes).hexdigest() == "74dcd938f4d7dacd8fe49ddf5fc6fa98056daecb5b87c3826d283e548842b689"
    trace_source = trace_bytes.decode()
    for signature in ["  public boolean combine() {\n",
                      "  public boolean normalize(IntOctagon p_clip_shape) throws Exception {\n",
                      "  public boolean pull_tight(PullTightAlgo p_pull_tight_algo) {\n"]:
        assert trace_source.count(signature) == 1
        trace_source = trace_source.replace(signature, signature + '''    // LX0001: preserve authored fixed copper and explicitly ignored nets.
    if (this.is_user_fixed() || this.has_ignored_nets()) {
      return false;
    }
''')
    trace = work / "PolylineTrace.java"
    trace.write_text(trace_source)
    classes = work / "classes"
    classes.mkdir()
    command = [str(javac), "--release", "25", "-cp", str(original), "-d", str(classes), str(java), str(batch), str(trace)]
    subprocess.run(command, check=True)
    replacements = {str(path.relative_to(classes)): path.read_bytes()
                    for path in classes.rglob("*.class")}
    expected = {"app/freerouting/management/RoutingJobSchedulerActionThread.class",
                "app/freerouting/management/RoutingJobSchedulerActionThread$1.class",
                "app/freerouting/management/RoutingJobSchedulerActionThread$2.class",
                "app/freerouting/autoroute/BatchAutorouter.class",
                "app/freerouting/autoroute/BatchAutorouter$1.class",
                "app/freerouting/board/PolylineTrace.class"}
    assert set(replacements) == expected, set(replacements)
    with zipfile.ZipFile(original) as old, zipfile.ZipFile(output, "w") as new:
        for info in old.infolist():
            if info.filename.startswith("META-INF/") and info.filename.endswith((".SF", ".RSA", ".DSA")):
                raise RuntimeError("Signed upstream JAR requires a different patch method")
            new.writestr(info, replacements.get(info.filename, old.read(info.filename)))
print("Built", output)
print("SHA256", hashlib.sha256(output.read_bytes()).hexdigest())
