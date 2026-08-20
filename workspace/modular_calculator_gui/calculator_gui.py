import tkinter as tk
from calculator_core import Calculator

class CalculatorGUI:
    def __init__(self, root):
        self.root = root
        self.root.title("Modular Calc")
        self.display = tk.Entry(root)
        self.display.insert(0, "0")
        self.display.pack()
        self.engine = Calculator()

        # Beispiel-Buttons
        tk.Button(root, text="+", command=lambda: self.calculate("+")).pack()
        tk.Button(root, text="-", command=lambda: self.calculate("-")).pack()
        tk.Button(root, text="√", command=lambda: self.calculate("sqrt")).pack()

    def calculate(self, op_symbol):
        try:
            current = float(self.display.get())
        except ValueError:
            current = 0.0
        # Die eigentliche Rechenlogik (inkl. Kettenberechnung) steckt in Calculator
        # (calculator_core.py) und wird dort unabhängig von der GUI getestet.
        result = self.engine.apply(op_symbol, current)
        self.display.delete(0, tk.END)
        self.display.insert(0, str(result))

if __name__ == "__main__":
    root = tk.Tk()
    CalculatorGUI(root)
    root.mainloop()
