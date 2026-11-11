FreeRouting 2.2 local headless ignored-net-class fix
=================================================

Date: 2026-11-11
Scope: tooling only. This patch does not alter the KiCad PCB, schematic,
netlist, or original upstream JAR. It changes the router's handling of fixed
copper, ignored net classes, and (with explicit properties) optional cleanup.

Defect verified in the official 2.2 JAR using javap:
- GlobalSettings accepts -inc heavy,critical and splits on commas.
- The merged CliSettings short-option mapper only handles -mp and -mt.
- GuiManager applies ignoreNetClasses to NetClass.is_ignored_by_autorouter.
- The headless scheduler never applies those flags.

Fix 1: at the beginning of RoutingJobSchedulerActionThread.thread_action(),
apply job.routerSettings.ignoreNetClasses, falling back to the legacy CLI
settings when the merged list is empty. Match class names without case or
surrounding whitespace. Log every ignored class and warn for missing names.
No ignored class names are hard-coded. Repeated -inc arguments overwrite;
use one comma-separated value: -inc heavy,critical.

Fix 2: the first smoke test then exposed global cleanup touching ignored
fixed traces and crashing in ShapeSearchTree.merge_entries_at_end.
BatchAutorouter.remove_tails now iterates only nonignored net numbers;
its cleanup optimization is restricted to that same net. PolylineTrace
combine, normalize and pull_tight preserve user-fixed or ignored traces.
Other routing behavior remains upstream. Fixed copper preservation requires
final KiCad connectivity and DRC validation after SES import.

Patch 3 adds two explicit, opt-in experiment properties, both false by default:
- -Dlx0001.areaObstacles=true enables conduction-area obstacles before routing.
  Structure.read_scope imports DSN planes with is_obstacle=false. The capsule
  exporter represents real fixed copper, so other nets must avoid these areas.
  Without this setting, the private experiment created shorts/crossings.
- -Dlx0001.skipCleanupPullTight=true skips opt_changed_area in remove_tails.
  Tail removal still runs; the skipped optional smoothing operation threw a
  null-net-array NPE in BasicBoard.check_trace_shape during pass 13.
These changes do not establish route correctness: preserve the original
KiCad copper, import only into a private copy first, refill, and check DRC.

Patch 4 corrects a second imported-plane assumption when areaObstacles=true:
Structure.read_scope creates plane nets with contains_plane=true. The
BatchAutorouter.autoroute_item shortcut then returns CONNECTED_TO_PLANE for
any connected set touching one area, even if other same-net islands remain.
Capsules represent finite original copper, so the scheduler now clears
contains_plane for all imported area nets in this explicit mode. Conductive
area geometry and obstacle behavior remain enabled. The raw KiCad zone
outlines must already have been removed by export_router_areas.py.

CLI spelling matters: '-mp 20 -mt 1' uses separate tokens. '-mp20' and
'-mt1' are silently ignored by the merged short-option parser. An explicit
job limit is accepted as --router.job_timeout=00:04:00.

Upstream source:
https://raw.githubusercontent.com/freerouting/freerouting/v2.2.0/src/main/java/app/freerouting/management/RoutingJobSchedulerActionThread.java
Source SHA256:
45b80a9b245fb5ed72a29fcf22460b038d0ad880f28ba56c31ffe4975c358137

Official original JAR:
https://github.com/freerouting/freerouting/releases/tag/v2.2.0
SHA256 c5642db8dbf00cf906a00e1c2099acc957a82346704e1bf6083e549383afdb27

Compiler: Eclipse Temurin 25.0.5+8, macOS aarch64 JDK, official Adoptium
asset API. Download archive SHA256 verified against its API metadata:
36dc14d797aaff6d89aab302cd053fdba6207dfdcf772052fa7b023a94b0e857
https://github.com/adoptium/temurin25-binaries/releases/download/jdk-25.0.5%2B8/OpenJDK25U-jdk_aarch64_mac_hotspot_25.0.5_8.tar.gz

Build command, from this directory:
python3 build_patch.py /tmp/lx0001-freerouting-2.2.jar /tmp/lx0001-jdk25/jdk-25.0.5+8/Contents/Home/bin/javac /tmp/lx0001-freerouting-2.2-patched4.jar

build_patch.py verifies the upstream input hashes, inserts the shown patches,
compiles only the three source files with --release 25, and replaces only
their six emitted classes in a separate JAR. All other entries are copied
without changes. The build does not overwrite the original JAR or run CAD.

Historical patch2 SHA256:
0c0485043d22959d2ee99a17252a9af78795233ed5567331b0bf1118c06a117b

Historical patch3 SHA256:
eb4b37247711117e6a275bfce2b84b388166fcd26851a60cb43fb644516ccda0

Current patch4 SHA256:
1820acd5c7d3f0b59ff9c328327251ba2cd1aa1aa844f5026bac10251a35c125

Smoke-test command (temporary output, no CAD import):
/tmp/lx0001-java25/jdk-25.0.5+8-jre/Contents/Home/bin/java -Xmx2g -Djava.awt.headless=true -jar /tmp/lx0001-freerouting-2.2-patched2.jar --gui.enabled=false -da -de /tmp/lx0001.dsn -do /tmp/lx0001-patch2-smoke.ses -mp 1 -mt 1 --router.optimizer.enabled=false -inc heavy,critical

Required observable evidence before routing:
LX0001 headless fix: ignoring net class 'heavy'.
LX0001 headless fix: ignoring net class 'critical'.

Patch2 smoke test result: both classes logged; one full pass completed in
4.53 seconds with 232 -> 163 reported unrouted connections (including
ignored-net connections). No ERROR, normalization, or null-pointer logs.
The router produced the temporary SES file; it was not imported into CAD.

Patch3 area-obstacle experiment: zero router ERROR logs, all 428 unique
original copper geometries preserved after private SES import and refill.
KiCad found 57 unconnected items, the four known PTH courtyard exceptions,
and one dangling ESP_EN track; no shorts, crossings, or clearance errors.
This was not selected for the main PCB. The exact result and limitations
are recorded in capsule-experiment-result.json. The companion original-wire
comparison still produced repeated +3V3 normalization errors and was stopped.

Additional upstream sources preserved here:
https://raw.githubusercontent.com/freerouting/freerouting/v2.2.0/src/main/java/app/freerouting/autoroute/BatchAutorouter.java
SHA256 22a1adeb33c29c5ed10421a83aff735692fd02fd7010c7e5e395a4d1786b8c84
https://raw.githubusercontent.com/freerouting/freerouting/v2.2.0/src/main/java/app/freerouting/board/PolylineTrace.java
SHA256 74dcd938f4d7dacd8fe49ddf5fc6fa98056daecb5b87c3826d283e548842b689

The complete upstream source and upstream LICENSE are preserved beside the
build script. This is a local derivative under the upstream AGPL license;
the full replacement source is reproducible from these files.

Repaired-baseline small-via experiment command:
/tmp/lx0001-java25/jdk-25.0.5+8-jre/Contents/Home/bin/java -Xmx2g -Djava.awt.headless=true -Dlx0001.areaObstacles=true -Dlx0001.skipCleanupPullTight=true -jar /tmp/lx0001-freerouting-2.2-patched3.jar --gui.enabled=false -da -de /tmp/lx0001-bank-areas-smallvia.dsn -do /tmp/lx0001-bank-areas-smallvia.ses -mp 20 -mt 1 --router.job_timeout=00:04:00 --router.optimizer.enabled=false -inc heavy,critical
