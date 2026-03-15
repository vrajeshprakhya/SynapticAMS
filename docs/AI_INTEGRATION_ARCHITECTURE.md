# SynapticAMS AI-Integration Branch Architecture

## Overview

The ai-integration branch contains **TWO parallel pipelines** for SPICE → Verilog-AMS conversion:

1. **AI Pipeline** (`pipeline.py`) - Uses LLM (Claude/Ollama) for code generation
2. **Programmatic Pipeline** (`pipeline_ext/complete_pipeline.py`) - Uses algorithmic model fitting

---

## 1. AI Pipeline Flow (pipeline.py)

```mermaid
flowchart TD
    Start([SPICE Netlist<br/>Input]) --> Flatten{Has<br/>.SUBCKT?}

    Flatten -->|Yes| SpiceFlattener[spice_flatten.py<br/>Flatten Subcircuits]
    Flatten -->|No| Parse
    SpiceFlattener --> Parse

    Parse[Parse Netlist<br/>parse_netlist]

    Parse --> FindSignal[Find Signal Source<br/>from .DC or heuristics]
    FindSignal --> FindOutput[Find Output Node<br/>Transistor drain heuristic]
    FindOutput --> FindVDD[Extract VDD<br/>from voltage sources]

    FindVDD --> RunNgspice[Run ngspice<br/>DC Sweep]

    RunNgspice --> NgspiceRunner[NgspiceRunner.dc_sweep<br/>Generate I/O data]

    NgspiceRunner --> AIAgent[AI Agent<br/>ai_agent.py]

    AIAgent --> CreateAgent{Backend<br/>Available?}

    CreateAgent -->|ANTHROPIC_API_KEY| Claude[Claude API<br/>Anthropic]
    CreateAgent -->|Ollama Running| Ollama[Ollama Local<br/>qwen2.5-coder:7b]
    CreateAgent -->|Neither| Error[Error: No Backend]

    Claude --> GenerateVA[Generate Verilog-AMS<br/>from netlist + DC data]
    Ollama --> GenerateVA

    GenerateVA --> Evaluate[Evaluate Model<br/>compute_nrmse]

    Evaluate --> CheckNRMSE{NRMSE <<br/>0.05?}

    CheckNRMSE -->|Yes| SaveVA[Save .va File]
    CheckNRMSE -->|No| IterCheck{Iteration <<br/>MAX_ITERATIONS?}

    IterCheck -->|Yes| Refine[Refine Model<br/>with error feedback]
    IterCheck -->|No| SaveVA

    Refine --> GenerateVA

    SaveVA --> End([Generated<br/>Verilog-AMS])

    style Start fill:#90EE90
    style End fill:#90EE90
    style AIAgent fill:#FFB6C1
    style Claude fill:#DDA0DD
    style Ollama fill:#DDA0DD
    style NgspiceRunner fill:#87CEEB
    style SpiceFlattener fill:#87CEEB
    style Error fill:#FF6B6B
```

---

## 2. Programmatic Pipeline Flow (pipeline_ext/complete_pipeline.py)

```mermaid
flowchart TD
    Start([SPICE Netlist<br/>Input]) --> Step1

    subgraph Step1["[1/8] Parse SPICE Netlist"]
        Parse[parse_spice_netlist<br/>graph_builder.py]
        Parse --> BuildGraph[build_bipartite_graph<br/>Devices ↔ Nets]
    end

    Step1 --> Step2

    subgraph Step2["[2/8] Analyze Structure"]
        AnalyzeBlocks[analyze_blocks<br/>circuit_analyzer.py]
        AnalyzeBlocks --> Classify{Classify<br/>Behavior}
        Classify --> Structural[STRUCTURAL_LINEAR<br/>Passive R/L/C only]
        Classify --> SmallSignal[SMALL_SIGNAL_LINEARIZABLE<br/>Amplifiers, buffers]
        Classify --> Nonlinear[NONLINEAR<br/>Comparators, switches]
    end

    Step2 --> Step3

    subgraph Step3["[3/8] Plan Simulations"]
        CreatePlanner[SimulationPlanner<br/>simulation_planner.py]
        CreatePlanner --> FindConstants[find_constant_nets]
        FindConstants --> PlanDC[plan_dc_sweep<br/>1D or 2D based on inputs]
        PlanDC --> IndependenceTest{Test Input<br/>Independence?}
        IndependenceTest -->|Coupled| Use2D[Plan 2D Sweep]
        IndependenceTest -->|Independent| Use1D[Plan 1D Sweeps]
    end

    Step3 --> Step4

    subgraph Step4["[4/8] Run ngspice"]
        RunSweeps[NgspiceRunner]
        RunSweeps --> DC1D[dc_sweep<br/>1D analysis]
        RunSweeps --> DC2D[dc_sweep_2d<br/>2D nested sweep]
        RunSweeps --> ACSweep[ac_sweep<br/>Frequency response]
        RunSweeps --> ExtractAC[extract_ac_params<br/>gm, gds, Cgs, etc.]
    end

    Step4 --> Step5

    subgraph Step5["[5/8] Fit Models"]
        FitModels[fit_transfer_function.py]
        FitModels --> Fit1D[1D: Linear/Poly/Piecewise]
        FitModels --> Fit2D[2D: Bilinear/Surface fit]
        FitModels --> FitAC[AC: Transfer function H(s)]
        FitModels --> FitSS[Small-signal: gm, gds model]
    end

    Step5 --> Step6

    subgraph Step6["[6/8] Generate Verilog-AMS"]
        VerilogGen[VerilogAMSGenerator<br/>verilog_ams_generator.py]
        VerilogGen --> GenLinear[Generate linear model<br/>V(out) <+ gain * V(in)]
        VerilogGen --> GenNonlinear[Generate nonlinear<br/>Piecewise/polynomial]
        VerilogGen --> GenSS[Generate small-signal<br/>with AC params]
    end

    Step6 --> Step7

    subgraph Step7["[7/8] Equivalence Checking"]
        EquivCheck[OSDIEquivalenceChecker<br/>equivalence_checker_osdi.py]
        EquivCheck --> CompileOSDI[Compile .va → .osdi<br/>OpenVAF]
        CompileOSDI --> SimBoth[Simulate SPICE +<br/>OSDI in ngspice]
        SimBoth --> Compare[Compare outputs<br/>abs_tol, rel_tol]
        Compare --> Report[Pass/Fail + metrics]
    end

    Step7 --> Step8

    subgraph Step8["[8/8] Save Files"]
        SaveAll[generator.save_all<br/>Write .va files]
    end

    Step8 --> End([Generated<br/>Verilog-AMS Modules<br/>+ Equivalence Report])

    style Start fill:#90EE90
    style End fill:#90EE90
    style EquivCheck fill:#FFB6C1
    style VerilogGen fill:#FFD700
    style RunSweeps fill:#87CEEB
    style FitModels fill:#DDA0DD
```

---

## 3. Module Interaction Sequence (Programmatic Pipeline)

```mermaid
sequenceDiagram
    participant User
    participant Main as complete_pipeline.py
    participant GB as graph_builder.py
    participant CA as circuit_analyzer.py
    participant SP as simulation_planner.py
    participant NG as NgspiceRunner
    participant FT as fit_transfer_function.py
    participant VG as VerilogAMSGenerator
    participant EC as EquivalenceChecker

    User->>Main: spice_to_verilog_ams(netlist)

    Note over Main: Step 1: Parse
    Main->>GB: parse_spice_netlist(netlist)
    GB-->>Main: devices[]
    Main->>GB: build_bipartite_graph(devices)
    GB-->>Main: graph (NetworkX)

    Note over Main: Step 2: Analyze
    Main->>CA: analyze_blocks(graph)
    CA->>CA: find_connected_components()
    CA->>CA: classify_behavior()
    CA->>CA: detect_inputs_outputs()
    CA-->>Main: blocks[] with behavior_class

    Note over Main: Step 3: Plan
    Main->>CA: find_constant_nets(graph)
    CA-->>Main: constant_nets
    Main->>SP: SimulationPlanner(graph, netlist)
    loop For each block
        Main->>SP: plan_dc_sweep(block)
        SP->>SP: test_independence()
        SP-->>Main: sweep_plans[]
    end

    Note over Main: Step 4: Simulate
    loop For each sweep_plan
        alt 2D Sweep
            Main->>NG: dc_sweep_2d(netlist, params)
            NG-->>Main: {var1: [], var2: [], out: 2D_array}
        else 1D Sweep
            Main->>NG: dc_sweep(netlist, params)
            NG-->>Main: {var: [], out: []}
        end
    end

    loop For structural_linear blocks
        Main->>NG: ac_sweep(netlist, params)
        NG-->>Main: {freq: [], mag: [], phase: []}
    end

    Note over Main: Step 5: Fit
    loop For each simulation_result
        alt 2D data
            Main->>FT: fit_transfer_function_2d(x1, x2, z)
        else 1D data
            Main->>FT: fit_transfer_function(x, y)
        end
        FT->>FT: try_linear_fit()
        FT->>FT: try_polynomial_fit()
        FT->>FT: try_piecewise_fit()
        FT-->>Main: model {type, coeffs, intent}
    end

    Note over Main: Step 6: Generate
    Main->>VG: VerilogAMSGenerator()
    loop For each fitted_model
        Main->>VG: generate_module(model, name)
        VG-->>Main: verilog_code
    end

    Note over Main: Step 7: Verify
    loop For each module
        Main->>EC: check_equivalence(spice, verilog, name)
        EC->>EC: compile_osdi()
        EC->>NG: simulate both
        NG-->>EC: results
        EC->>EC: compare_outputs()
        EC-->>Main: EquivalenceResult
    end

    Note over Main: Step 8: Save
    Main->>VG: save_all(output_dir)
    VG-->>Main: saved_files[]

    Main-->>User: files + report
```

---

## 4. AI Pipeline Sequence (pipeline.py)

```mermaid
sequenceDiagram
    participant User
    participant Pipeline as pipeline.py
    participant SF as spice_flatten.py
    participant NG as NgspiceRunner
    participant AI as ai_agent.py
    participant LLM as Claude/Ollama

    User->>Pipeline: run_pipeline(netlist)

    opt Has .SUBCKT
        Pipeline->>SF: flatten_netlist(netlist)
        SF-->>Pipeline: flat_netlist
    end

    Pipeline->>Pipeline: parse_netlist(netlist)
    Note over Pipeline: Extract signal_source,<br/>output_node, vdd

    Pipeline->>NG: NgspiceRunner()
    Pipeline->>NG: dc_sweep(netlist, params)
    NG-->>Pipeline: {input: x[], output: y[]}

    Pipeline->>AI: create_agent()
    AI->>AI: Check ANTHROPIC_API_KEY
    AI->>AI: Check Ollama running
    AI-->>Pipeline: agent (Claude or Ollama)

    Pipeline->>AI: generate(netlist, x, y, info)
    AI->>AI: _build_prompt(netlist, x, y, info)
    AI->>LLM: Send prompt
    LLM-->>AI: Verilog-AMS code
    AI-->>Pipeline: va_code

    Pipeline->>AI: evaluate_va_code(code, x, output)
    AI-->>Pipeline: y_model[]

    Pipeline->>AI: compute_nrmse(y, y_model)
    AI-->>Pipeline: nrmse

    loop While nrmse > 0.05 AND iteration < 3
        Pipeline->>AI: refine(netlist, x, y, info, code, nrmse)
        AI->>AI: _build_refine_prompt()
        Note over AI: Include worst-error points<br/>for targeted improvement
        AI->>LLM: Send refinement prompt
        LLM-->>AI: Improved code
        AI-->>Pipeline: new_code

        Pipeline->>AI: evaluate_va_code(new_code)
        Pipeline->>AI: compute_nrmse()
    end

    Pipeline->>Pipeline: save_va_file(code, output_dir)
    Pipeline-->>User: path_to_va_file
```

---

## 5. SPICE Flattening Architecture (spice_flatten.py)

```mermaid
flowchart TD
    Start([Raw SPICE<br/>Netlist]) --> Init[SpiceFlattener<br/>Initialize]

    Init --> ProcessCont[Process Line<br/>Continuations '+']

    ProcessCont --> ParseLines[Parse Lines<br/>Iteratively]

    ParseLines --> LineType{Line Type?}

    LineType -->|.SUBCKT| ParseSubckt[Parse Subcircuit<br/>Definition]
    LineType -->|.ENDS| EndSubckt[End Subcircuit]
    LineType -->|.INCLUDE/.LIB| ProcessInclude[Process Include<br/>Recursive parse]
    LineType -->|.MODEL| TrackModel[Track Model Name<br/>Don't rename later]
    LineType -->|.GLOBAL| AddGlobal[Add to<br/>global_nodes set]
    LineType -->|.END| StopParsing[Stop Parsing<br/>Ignore rest]
    LineType -->|X instance| ExpandSubckt[Expand Subcircuit<br/>Instance]
    LineType -->|Device| AddDevice[Add to<br/>top_level_lines]
    LineType -->|Comment *| Skip[Skip]

    ParseSubckt --> StoreSubckt[Store in<br/>subcircuits dict]
    StoreSubckt --> ParseLines

    ExpandSubckt --> GetDef[Get Subcircuit<br/>Definition]
    GetDef --> MapPorts[Map External Nodes<br/>to Internal Ports]
    MapPorts --> RenameNodes[Rename Internal Nodes<br/>with hierarchy prefix]
    RenameNodes --> HandleSpecial{Special<br/>Device?}

    HandleSpecial -->|K mutual| RenameDeviceRefs[Rename L1/L2<br/>as device names]
    HandleSpecial -->|F/H source| RenameVnam[Rename Vnam<br/>as device name]
    HandleSpecial -->|Q BJT 4-term| RenameSubstrate[Rename 4th<br/>substrate node]
    HandleSpecial -->|Normal| NormalRename[Standard<br/>node rename]

    RenameDeviceRefs --> AppendExpanded[Append expanded<br/>lines to output]
    RenameVnam --> AppendExpanded
    RenameSubstrate --> AppendExpanded
    NormalRename --> AppendExpanded

    AppendExpanded --> ParseLines

    StopParsing --> Combine[Combine title +<br/>top_level_lines +<br/>.END]

    Combine --> End([Flat Netlist<br/>No .SUBCKT])

    style Start fill:#90EE90
    style End fill:#90EE90
    style ExpandSubckt fill:#FFD700
    style HandleSpecial fill:#FFB6C1
```

---

## 6. Circuit Classification & Analysis Mode Selection

```mermaid
flowchart TD
    Start([Extracted Block]) --> CheckDevices{Has Active<br/>Devices?}

    CheckDevices -->|No| Passive[Passive Only<br/>R/L/C]
    CheckDevices -->|Yes| CheckType{Device<br/>Configuration?}

    Passive --> CountReactive1{Count C + L}
    CountReactive1 -->|0| StructLinDC[STRUCTURAL_LINEAR<br/>DC only]
    CountReactive1 -->|1+| StructLinAC[STRUCTURAL_LINEAR<br/>DC + AC]

    CheckType -->|Comparator/Switch| NonlinearPath[NONLINEAR]
    CheckType -->|Amplifier/Buffer| LinearizePath[SMALL_SIGNAL_LINEARIZABLE]

    NonlinearPath --> NonlinAnalysis[Required:<br/>DC + AC + Transient]

    LinearizePath --> CountReactive2{Count C + L}
    CountReactive2 -->|0| SSDC[DC only<br/>Pure resistive amp]
    CountReactive2 -->|1+| SSAC[DC + AC<br/>Frequency response]

    StructLinDC --> PlanSweep
    StructLinAC --> PlanSweep
    NonlinAnalysis --> PlanSweep
    SSDC --> PlanSweep
    SSAC --> PlanSweep

    PlanSweep[Plan Simulations<br/>simulation_planner.py]

    PlanSweep --> CheckInputs{Number of<br/>Signal Inputs?}

    CheckInputs -->|1| Plan1D[1D DC Sweep]
    CheckInputs -->|2| TestIndep{Test<br/>Independence?}
    CheckInputs -->|3+| PlanPoints[Point-by-point<br/>3D+ grid]

    TestIndep -->|Coupled| Plan2D[2D Nested<br/>DC Sweep]
    TestIndep -->|Independent| Plan1DMulti[Multiple 1D<br/>Sweeps]

    Plan1D --> Execute[Execute via<br/>NgspiceRunner]
    Plan2D --> Execute
    Plan1DMulti --> Execute
    PlanPoints --> Execute

    Execute --> End([Simulation<br/>Results])

    style Start fill:#90EE90
    style End fill:#90EE90
    style NonlinearPath fill:#FF6B6B
    style LinearizePath fill:#87CEEB
    style Passive fill:#90EE90
```

---

## 7. Complete File Structure (ai-integration branch)

```mermaid
graph LR
    subgraph Root["~/SynapticAMS/"]
        direction TB
        SF[spice_flatten.py<br/>676 lines]
        PP[pipeline.py<br/>560 lines<br/>AI Pipeline]
        NR[ngspice_runner.py<br/>804 lines]
        AA[ai_agent.py<br/>~300 lines]
    end

    subgraph PipelineExt["pipeline_ext/"]
        direction TB
        CP[complete_pipeline.py<br/>477 lines]
        CA[circuit_analyzer.py<br/>26,112 bytes]
        SP[simulation_planner.py<br/>17,455 bytes]
        GB[graph_builder.py<br/>2,823 bytes]
        VG[verilog_ams_generator.py<br/>25,648 bytes]
        FT[fit_transfer_function.py<br/>21,871 bytes]
        ES[extract_small_signal_model.py]
    end

    subgraph EquivChecker["equivalence_checker/"]
        direction TB
        EC[equivalence_checker.py<br/>1,562 lines]
        ID[independence_detector.py<br/>245 lines]
        AMS[analysis_mode_selector.py]
    end

    subgraph Tests["tests/"]
        TP[test_pipeline.py<br/>39,719 bytes]
    end

    Root --> PipelineExt
    Root --> EquivChecker
    Root --> Tests

    PP -.-> AA
    PP -.-> NR
    PP -.-> SF

    CP --> GB
    CP --> CA
    CP --> SP
    CP --> NR
    CP --> FT
    CP --> VG
    CP --> EC

    style SF fill:#87CEEB
    style PP fill:#FFD700
    style CP fill:#90EE90
    style EC fill:#FFB6C1
```

---

## 8. Data Flow Overview

```mermaid
flowchart LR
    subgraph Input
        SPICE[SPICE Netlist<br/>.cir file]
    end

    subgraph Preprocessing
        Flatten[Flatten<br/>Subcircuits]
        Parse[Parse to<br/>Graph]
    end

    subgraph Analysis
        Blocks[Extract<br/>Blocks]
        Classify[Classify<br/>Behavior]
        Plan[Plan<br/>Simulations]
    end

    subgraph Simulation
        DC[DC Sweep<br/>ngspice]
        AC[AC Sweep<br/>ngspice]
    end

    subgraph Modeling
        Fit[Fit Transfer<br/>Functions]
        AIGen[AI Generate<br/>Optional]
    end

    subgraph Output
        VerilogAMS[Verilog-AMS<br/>.va files]
        Report[Equivalence<br/>Report]
    end

    SPICE --> Flatten
    Flatten --> Parse
    Parse --> Blocks
    Blocks --> Classify
    Classify --> Plan
    Plan --> DC
    Plan --> AC
    DC --> Fit
    AC --> Fit
    DC --> AIGen
    Fit --> VerilogAMS
    AIGen --> VerilogAMS
    VerilogAMS --> Report

    style SPICE fill:#90EE90
    style VerilogAMS fill:#90EE90
    style Report fill:#90EE90
```

---

## 9. Equivalence Checking Flow

```mermaid
flowchart TD
    Start([SPICE Netlist +<br/>Verilog-AMS Code]) --> Compile[Compile .va → .osdi<br/>OpenVAF]

    Compile --> CompileOK{Compilation<br/>Success?}

    CompileOK -->|No| CompileErr[Return<br/>Compilation Error]
    CompileOK -->|Yes| GenVectors[Generate Test<br/>Vectors]

    GenVectors --> Strategy{Test<br/>Strategy?}

    Strategy -->|Grid| GridGen[Grid sampling<br/>e.g. 50×50 = 2500 pts]
    Strategy -->|Random| RandomGen[Monte Carlo<br/>LHS sampling]
    Strategy -->|Corners| CornerGen[Corner cases<br/>Min/Max combinations]
    Strategy -->|Adaptive| AdaptGen[Adaptive<br/>Error-focused]

    GridGen --> SimSPICE[Simulate SPICE<br/>DC sweep]
    RandomGen --> SimSPICE
    CornerGen --> SimSPICE
    AdaptGen --> SimSPICE

    SimSPICE --> SimOSDI[Simulate OSDI<br/>DC sweep]

    SimOSDI --> Compare[Compare Outputs<br/>Point-by-point]

    Compare --> CalcMetrics[Calculate Metrics<br/>RMSE, MAE, Correlation]

    CalcMetrics --> CheckPass{Within<br/>Tolerances?}

    CheckPass -->|Yes| Pass[PASSED<br/>Model validated]
    CheckPass -->|No| Fail[FAILED<br/>Show mismatches]

    Pass --> SaveTB[Save Testbenches<br/>for debugging]
    Fail --> SaveTB

    SaveTB --> End([Equivalence<br/>Result + Report])

    CompileErr --> End

    style Start fill:#90EE90
    style End fill:#90EE90
    style Pass fill:#90EE90
    style Fail fill:#FF6B6B
```

---

## 10. AI Agent Backend Selection

```mermaid
flowchart TD
    Start([create_agent]) --> CheckAnthropic{ANTHROPIC_API_KEY<br/>set?}

    CheckAnthropic -->|Yes| UseAnthropic[Use Anthropic Client<br/>Claude API]
    CheckAnthropic -->|No| CheckOllama{Ollama<br/>running?}

    CheckOllama -->|Yes| UseOllama[Use Ollama Client<br/>Local LLM]
    CheckOllama -->|No| NoBackend[Raise Error<br/>No backend available]

    UseAnthropic --> Ready[Agent Ready]
    UseOllama --> Ready

    Ready --> Generate[generate<br/>Initial Verilog-AMS]

    Generate --> Evaluate[evaluate_va_code<br/>Run in ngspice]

    Evaluate --> ComputeNRMSE[compute_nrmse<br/>Compare to SPICE]

    ComputeNRMSE --> CheckThreshold{NRMSE <<br/>0.05?}

    CheckThreshold -->|Yes| Done[Return Code]
    CheckThreshold -->|No| CheckIter{Iteration <<br/>3?}

    CheckIter -->|Yes| Refine[refine<br/>Error-focused prompt]
    CheckIter -->|No| Done

    Refine --> Generate

    Done --> End([Final<br/>Verilog-AMS])

    style Start fill:#90EE90
    style End fill:#90EE90
    style UseAnthropic fill:#DDA0DD
    style UseOllama fill:#87CEEB
    style NoBackend fill:#FF6B6B
```

---

## Summary

The ai-integration branch provides:

1. **AI Pipeline** (`pipeline.py`)
   - LLM-based code generation
   - Iterative refinement with error feedback
   - Supports Claude API and Ollama local LLM

2. **Programmatic Pipeline** (`pipeline_ext/complete_pipeline.py`)
   - 8-step algorithmic pipeline
   - Automatic circuit classification
   - Model fitting (linear, polynomial, piecewise)
   - OSDI-based equivalence checking

3. **Shared Infrastructure**
   - `spice_flatten.py` - SPICE 3F5 compliant netlist flattening
   - `ngspice_runner.py` - DC/AC sweep execution
   - `equivalence_checker/` - Model validation

Both pipelines produce validated Verilog-AMS behavioral models from SPICE netlists.
