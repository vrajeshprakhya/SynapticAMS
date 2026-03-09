# SynapticAMS Pipeline Architecture

## Complete Pipeline Flow

```mermaid
flowchart TD
    Start([SPICE Netlist Input]) --> GraphBuilder[Graph Builder<br/>graph_builder.py]

    GraphBuilder --> CircuitAnalyzer[Circuit Analyzer<br/>circuit_analyzer.py]

    CircuitAnalyzer --> BlockExtraction{Extract Blocks}
    BlockExtraction --> ClassifyBehavior[Classify Behavior<br/>STRUCTURAL_LINEAR<br/>SMALL_SIGNAL_LINEARIZABLE<br/>NONLINEAR]

    ClassifyBehavior --> TopologyAnalysis[Topology Analysis<br/>Count C/L Elements<br/>Detect Active Devices]

    TopologyAnalysis --> DetermineAnalyses[Determine Required Analyses<br/>DC / DC+AC / DC+AC+Tran]

    DetermineAnalyses --> SimPlanner[Simulation Planner<br/>simulation_planner.py]

    SimPlanner --> IndependenceCheck{Test Input<br/>Independence}

    IndependenceCheck -->|Coupled| Use2D[Use 2D DC Sweep]
    IndependenceCheck -->|Independent| Use1D[Use 1D DC Sweeps]

    Use2D --> DCSimulation[DC Simulation<br/>ngspice_runner.py]
    Use1D --> DCSimulation

    DCSimulation --> DCResults[DC Sweep Results<br/>2D or 1D Arrays]

    DCResults --> ModelFitting[Model Fitting<br/>fit_transfer_function_dc_sweep.py]

    ModelFitting --> FitType{Fit Type}

    FitType -->|Linear| LinearFit[Linear Regression<br/>Av, offset]
    FitType -->|Polynomial| PolyFit[Polynomial Fit<br/>degree 2-5]
    FitType -->|Piecewise| PiecewiseFit[Piecewise Linear<br/>Multiple regions]

    LinearFit --> VerilogGen[Verilog-AMS Generator<br/>verilog_ams_generator.py]
    PolyFit --> VerilogGen
    PiecewiseFit --> VerilogGen

    VerilogGen --> GenerateCode[Generate Behavioral Code<br/>analog begin...end]

    GenerateCode --> EquivCheck[Equivalence Checker<br/>equivalence_checker.py]

    EquivCheck --> CompileOSDI[Compile to OSDI<br/>OpenVAF Compiler]

    CompileOSDI --> RunEquiv{Run Equivalence<br/>Checking}

    RunEquiv --> DCEquiv[DC Equivalence<br/>DC Sweep Both Sides]

    DCEquiv --> ACEquiv{AC Required?}
    ACEquiv -->|Yes| RunAC[AC Equivalence<br/>Frequency Response]
    ACEquiv -->|No| TranEquiv

    RunAC --> TranEquiv{Transient<br/>Required?}

    TranEquiv -->|Yes| RunTran[Transient Equivalence<br/>Step Response]
    TranEquiv -->|No| CompareResults

    RunTran --> CompareResults[Compare Results<br/>Check Tolerances]

    CompareResults --> ValidationCheck{All Tests<br/>Pass?}

    ValidationCheck -->|Pass| SaveOutput[Save Verilog-AMS<br/>+ Test Report]
    ValidationCheck -->|Fail| GenerateReport[Generate Failure Report<br/>Show Mismatches]

    SaveOutput --> End([Validated Verilog-AMS<br/>Modules + Report])
    GenerateReport --> End

    style Start fill:#90EE90
    style End fill:#90EE90
    style GraphBuilder fill:#87CEEB
    style CircuitAnalyzer fill:#87CEEB
    style SimPlanner fill:#87CEEB
    style ModelFitting fill:#87CEEB
    style VerilogGen fill:#87CEEB
    style EquivCheck fill:#FFB6C1
    style CompileOSDI fill:#FFB6C1
    style DCEquiv fill:#FFB6C1
    style RunAC fill:#FFB6C1
    style RunTran fill:#FFB6C1
    style CompareResults fill:#FFB6C1
    style ValidationCheck fill:#FFD700
    style SaveOutput fill:#90EE90
```

## Detailed Equivalence Checking Flow

```mermaid
flowchart TD
    Start([SPICE Netlist +<br/>Verilog-AMS Code]) --> InitChecker[Initialize Equivalence Checker<br/>Set tolerances: abs_tol, rel_tol]

    InitChecker --> DetectSources[Detect Source Types<br/>Voltage V vs Current I]

    DetectSources --> ExtractRanges[Extract Ranges from Netlist<br/>All VDD supplies<br/>All current sources]

    ExtractRanges --> GenVectors[Generate Test Vectors<br/>Grid/Random/Corners/Adaptive]

    GenVectors --> DimCheck{Dimensions?}

    DimCheck -->|1D| Use1DSweep[Build 1D DC Sweep<br/>Testbench]
    DimCheck -->|2D| Use2DSweep[Build 2D DC Sweep<br/>Testbench]
    DimCheck -->|3D+| UsePointByPoint[Build Point-by-Point<br/>Testbenches]

    Use1DSweep --> SimSPICE[Simulate SPICE Side<br/>ngspice with subcircuit]
    Use2DSweep --> SimSPICE
    UsePointByPoint --> SimSPICE

    SimSPICE --> SPICEResults[SPICE DC Results<br/>All test vectors]

    SPICEResults --> CompileVA[Compile Verilog-A to OSDI<br/>openvaf command]

    CompileVA --> CompileCheck{Compilation<br/>Success?}

    CompileCheck -->|Fail| CompileError[Return Compilation Error]
    CompileCheck -->|Success| BuildOSDI{Build OSDI<br/>Testbench}

    BuildOSDI -->|1D| OSDI1D[OSDI 1D DC Sweep<br/>pre_osdi + dc command]
    BuildOSDI -->|2D| OSDI2D[OSDI 2D DC Sweep<br/>pre_osdi + nested dc]
    BuildOSDI -->|3D+| OSDIPoint[OSDI Point-by-Point<br/>Individual simulations]

    OSDI1D --> SimVAMS[Simulate Verilog-AMS Side<br/>ngspice with OSDI model]
    OSDI2D --> SimVAMS
    OSDIPoint --> SimVAMS

    SimVAMS --> VAMSResults[Verilog-AMS DC Results<br/>All test vectors]

    VAMSResults --> SaveTestbenches{Save<br/>Testbenches?}

    SaveTestbenches -->|Yes| SaveTB[Save Representative<br/>Testbenches + Masters]
    SaveTestbenches -->|No| CompareOutputs

    SaveTB --> CompareOutputs[Compare SPICE vs VAMS<br/>Point-by-point]

    CompareOutputs --> CalcErrors[Calculate Errors<br/>Absolute & Relative]

    CalcErrors --> CheckTol{Within<br/>Tolerances?}

    CheckTol -->|Yes| CalcMetrics[Calculate Metrics<br/>Correlation, RMSE, MAE]
    CheckTol -->|No| Fail[Mark as FAILED<br/>Record mismatches]

    CalcMetrics --> CheckCorr{Correlation ><br/>Threshold?}

    CheckCorr -->|Yes| Pass[Mark as PASSED<br/>All checks good]
    CheckCorr -->|No| Fail

    Pass --> GenReport[Generate HTML Report<br/>Show metrics + plots]
    Fail --> GenReport

    GenReport --> End([Equivalence Result +<br/>Testbenches + Report])
    CompileError --> End

    style Start fill:#90EE90
    style End fill:#90EE90
    style InitChecker fill:#87CEEB
    style DetectSources fill:#87CEEB
    style ExtractRanges fill:#87CEEB
    style GenVectors fill:#87CEEB
    style SimSPICE fill:#DDA0DD
    style CompileVA fill:#FFB6C1
    style SimVAMS fill:#DDA0DD
    style CompareOutputs fill:#FFD700
    style CalcErrors fill:#FFD700
    style CalcMetrics fill:#FFD700
    style Pass fill:#90EE90
    style Fail fill:#FF6B6B
```

## Module Interaction Sequence

```mermaid
sequenceDiagram
    participant User
    participant Pipeline as complete_pipeline.py
    participant Graph as graph_builder.py
    participant Analyzer as circuit_analyzer.py
    participant Planner as simulation_planner.py
    participant NgSpice as ngspice_runner.py
    participant Fitter as fit_transfer_function.py
    participant VerilogGen as verilog_ams_generator.py
    participant EquivChk as equivalence_checker.py
    participant OpenVAF as OpenVAF Compiler

    User->>Pipeline: spice_to_verilog_ams(netlist)

    Pipeline->>Graph: build_graph(netlist)
    Graph-->>Pipeline: netlist_graph

    Pipeline->>Analyzer: extract_blocks(graph)
    Analyzer->>Analyzer: Classify behavior
    Analyzer->>Analyzer: Count C/L elements
    Analyzer->>Analyzer: Determine required analyses
    Analyzer-->>Pipeline: blocks with metadata

    loop For each block
        Pipeline->>Planner: plan_simulation(block)

        Planner->>Analyzer: detect_source_types()
        Analyzer-->>Planner: source_types [V, I, ...]

        Planner->>Planner: Test independence
        Planner-->>Pipeline: simulation_plan (1D/2D)

        Pipeline->>NgSpice: dc_sweep(netlist, params)
        NgSpice-->>Pipeline: dc_results

        Pipeline->>Fitter: fit_model(dc_results)
        Fitter->>Fitter: Try linear fit
        alt Linear fit good
            Fitter-->>Pipeline: linear_model
        else Need polynomial
            Fitter->>Fitter: Fit polynomial
            Fitter-->>Pipeline: poly_model
        else Need piecewise
            Fitter->>Fitter: Fit piecewise
            Fitter-->>Pipeline: piecewise_model
        end

        Pipeline->>VerilogGen: generate_verilog_ams(model)
        VerilogGen-->>Pipeline: verilog_code

        Pipeline->>EquivChk: check_equivalence(spice, verilog, block_info)

        EquivChk->>EquivChk: Generate test vectors
        EquivChk->>EquivChk: Detect source types
        EquivChk->>EquivChk: Extract ranges

        EquivChk->>NgSpice: Simulate SPICE (DC sweep)
        NgSpice-->>EquivChk: spice_results

        EquivChk->>OpenVAF: Compile Verilog-A
        OpenVAF-->>EquivChk: OSDI binary

        EquivChk->>NgSpice: Simulate OSDI (DC sweep)
        NgSpice-->>EquivChk: vams_results

        EquivChk->>EquivChk: Compare results
        EquivChk->>EquivChk: Calculate metrics

        alt All checks pass
            EquivChk-->>Pipeline: PASSED + metrics
            Pipeline->>Pipeline: Save Verilog-AMS
        else Checks fail
            EquivChk-->>Pipeline: FAILED + details
            Pipeline->>Pipeline: Generate error report
        end
    end

    Pipeline->>Pipeline: Generate HTML report
    Pipeline-->>User: Output files + report
```

## Data Flow Architecture

```mermaid
graph LR
    subgraph Input
        A[SPICE Netlist<br/>.cir file]
    end

    subgraph "Graph Analysis"
        B[NetworkX Graph<br/>Nodes + Edges]
        C[Block Subgraphs<br/>Connected Components]
    end

    subgraph "Block Metadata"
        D[Inputs/Outputs<br/>Simulation Axes]
        E[Behavior Class<br/>Linear/Nonlinear]
        F[Required Analyses<br/>DC/AC/Tran]
        G[Source Types<br/>V/I detection]
    end

    subgraph "Simulation Planning"
        H[Test Vectors<br/>1D/2D/3D Grid]
        I[Voltage Ranges<br/>From VDD]
        J[Current Ranges<br/>From I sources]
        K[Independence<br/>Result]
    end

    subgraph "DC Simulation"
        L[SPICE Results<br/>N-dimensional Array]
        M[Testbenches<br/>Master + Individual]
    end

    subgraph "Model Fitting"
        N[Linear Coefficients<br/>Av, offset]
        O[Polynomial Coefficients<br/>a0..a5]
        P[Piecewise Segments<br/>Breakpoints + slopes]
    end

    subgraph "Verilog-AMS"
        Q[Behavioral Code<br/>.va file]
        R[OSDI Binary<br/>.osdi file]
    end

    subgraph "Equivalence Results"
        S[DC Comparison<br/>Pass/Fail]
        T[AC Comparison<br/>Pass/Fail]
        U[Transient Comparison<br/>Pass/Fail]
        V[HTML Report<br/>Metrics + Plots]
    end

    subgraph Output
        W[Validated Modules<br/>.va files]
        X[Testbenches<br/>Saved files]
        Y[Documentation<br/>HTML report]
    end

    A --> B
    B --> C
    C --> D
    C --> E
    C --> F
    D --> G

    D --> H
    E --> H
    G --> I
    G --> J
    H --> K

    H --> L
    I --> L
    J --> L
    L --> M

    L --> N
    L --> O
    L --> P

    N --> Q
    O --> Q
    P --> Q
    Q --> R

    R --> S
    F --> T
    F --> U

    S --> V
    T --> V
    U --> V

    Q --> W
    M --> X
    V --> Y

    style A fill:#90EE90
    style B fill:#87CEEB
    style C fill:#87CEEB
    style L fill:#DDA0DD
    style Q fill:#FFB6C1
    style R fill:#FFB6C1
    style S fill:#FFD700
    style V fill:#FFD700
    style W fill:#90EE90
```

## Circuit Classification Decision Tree

```mermaid
graph TD
    Start([Analyze Block<br/>Topology]) --> HasTransistors{Has Active<br/>Devices?}

    HasTransistors -->|No| CheckReactive1{Has C or L?}
    HasTransistors -->|Yes| CheckNonlinear{Has Comparator<br/>or Switch?}

    CheckReactive1 -->|Yes| StructuralLinear[STRUCTURAL_LINEAR<br/>Pure passive filter]
    CheckReactive1 -->|No| StructuralLinear

    CheckNonlinear -->|Yes| Nonlinear[NONLINEAR<br/>Comparator/Switch/Limiter]
    CheckNonlinear -->|No| SmallSignal[SMALL_SIGNAL_LINEARIZABLE<br/>Amplifier/Buffer]

    StructuralLinear --> CountReactive1{Count<br/>C + L}
    SmallSignal --> CountReactive2{Count<br/>C + L}
    Nonlinear --> NonlinearAnalyses

    CountReactive1 -->|0| DCOnly1[Required: DC only]
    CountReactive1 -->|1| DCAC1[Required: DC + AC]
    CountReactive1 -->|2+| DCACTran1[Required: DC + AC + Tran]

    CountReactive2 -->|0| DCOnly2[Required: DC only]
    CountReactive2 -->|1| DCAC2[Required: DC + AC]
    CountReactive2 -->|2+| CheckInductors{Has<br/>Inductors?}

    CheckInductors -->|Yes| DCACTran2[Required: DC + AC + Tran<br/>Ringing possible]
    CheckInductors -->|No| DCAC3[Required: DC + AC<br/>Multi-pole response]

    NonlinearAnalyses[Required: DC + AC + Tran<br/>Switching behavior]

    DCOnly1 --> End1([Fast: DC sweep only])
    DCOnly2 --> End1
    DCAC1 --> End2([Medium: DC + AC])
    DCAC2 --> End2
    DCAC3 --> End2
    DCACTran1 --> End3([Complete: All analyses])
    DCACTran2 --> End3
    NonlinearAnalyses --> End3

    style Start fill:#90EE90
    style StructuralLinear fill:#87CEEB
    style SmallSignal fill:#87CEEB
    style Nonlinear fill:#FFB6C1
    style End1 fill:#90EE90
    style End2 fill:#FFD700
    style End3 fill:#FF6B6B
```

## Performance Optimization: Point-by-Point vs DC Sweep

```mermaid
graph TB
    subgraph "Old Approach: Point-by-Point"
        A1[Test Vector 1<br/>V1=0.0, V2=0.0] --> B1[Build Testbench 1]
        A2[Test Vector 2<br/>V1=0.0, V2=0.036] --> B2[Build Testbench 2]
        A3[Test Vector 3<br/>V1=0.0, V2=0.072] --> B3[Build Testbench 3]
        ADots[...] --> BDots[...]
        A2500[Test Vector 2500<br/>V1=1.8, V2=1.8] --> B2500[Build Testbench 2500]

        B1 --> C1[Run ngspice 1]
        B2 --> C2[Run ngspice 2]
        B3 --> C3[Run ngspice 3]
        BDots --> CDots[...]
        B2500 --> C2500[Run ngspice 2500]

        C1 --> D1[Result 1]
        C2 --> D2[Result 2]
        C3 --> D3[Result 3]
        CDots --> DDots[...]
        C2500 --> D2500[Result 2500]

        D1 --> E[Combine Results]
        D2 --> E
        D3 --> E
        DDots --> E
        D2500 --> E

        E --> F1[Time: ~600 seconds<br/>10 minutes]
    end

    subgraph "New Approach: DC Sweep"
        G[All Test Vectors<br/>2500 points] --> H[Build ONE Master<br/>Testbench]

        H --> I[dc V1 0 1.8 0.036<br/>V2 0 1.8 0.036]

        I --> J[Run ngspice ONCE]

        J --> K[All 2500 Results<br/>in one shot]

        K --> L[Time: ~21 seconds<br/>29× faster!]
    end

    style F1 fill:#FF6B6B
    style L fill:#90EE90
```
