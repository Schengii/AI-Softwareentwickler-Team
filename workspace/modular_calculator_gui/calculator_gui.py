import tkinter as tk
from calculator_core import OperationFactory

class CalculatorGUI:
    def __init__(self, root):
        self.root = root
        self.root.title("Modular Calc")
        self.display = tk.Entry(root)
        self.display.pack()
        
        # Beispiel-Buttons
        tk.Button(root, text="+", command=lambda: self.calculate("+")).pack()
        tk.Button(root, text="√", command=lambda: self.calculate("sqrt")).pack()

    def calculate(self, op_symbol):
        val = float(self.display.get())
        op = OperationFactory.get_operation(op_symbol)
        if op:
            result = op.execute(val)
            self.display.delete(0, tk.END)
            self.display.insert(0, str(result))

if __name__ == "__main__":
    root = tk.Tk()
    CalculatorGUI(root)
    root.mainloop()
