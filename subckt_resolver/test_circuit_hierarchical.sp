* Test circuit with DFF instantiation - HIERARCHICAL VERSION

* Simple MOSFET models
.model nmos NMOS (level=1 vto=0.7 kp=120u gamma=0.4 phi=0.7)
.model pmos PMOS (level=1 vto=-0.7 kp=40u gamma=0.4 phi=0.7)

* Simple inverter subcircuit
.SUBCKT INV IN OUT VDD GND
M1 OUT IN VDD VDD pmos W=2u L=0.5u
M2 OUT IN GND GND nmos W=1u L=0.5u
.ENDS

* NAND gate subcircuit
.SUBCKT NAND2 A B OUT VDD GND
M1 OUT A VDD VDD pmos W=2u L=0.5u
M2 OUT B VDD VDD pmos W=2u L=0.5u
M3 OUT A net1 GND nmos W=2u L=0.5u
M4 net1 B GND GND nmos W=2u L=0.5u
.ENDS

* D Flip-Flop using NAND gates
.SUBCKT DFF D CLK Q QB VDD GND
X1 D CLK n1 VDD GND NAND2
X2 DB CLK n2 VDD GND NAND2
X3 n1 n4 n3 VDD GND NAND2
X4 n2 n3 n4 VDD GND NAND2
X5 n3 CLK Q VDD GND NAND2
X6 n4 CLK QB VDD GND NAND2
X7 D DB VDD GND INV
.ENDS

* Top-level circuit
VDD VDD GND DC 1.8
VIN D_IN GND PULSE(0 1.8 0 1n 1n 10n 20n)
VCLK CLK_IN GND PULSE(0 1.8 0 1n 1n 5n 10n)

* Ground is node 0
.global 0 GND

* Instantiate two DFFs (HIERARCHICAL)
X_DFF1 D_IN CLK_IN Q1 QB1 VDD GND DFF
X_DFF2 Q1 CLK_IN Q2 QB2 VDD GND DFF

* Analysis
.TRAN 0.1n 100n

* Control commands for ngspice
.control
run
print v(D_IN) v(CLK_IN) v(Q1) v(QB1) v(Q2) v(QB2) > hierarchical_results.txt
write test_hierarchical.raw v(D_IN) v(CLK_IN) v(Q1) v(QB1) v(Q2) v(QB2)
echo "Hierarchical simulation completed - 1140 points"
quit
.endc

.END
