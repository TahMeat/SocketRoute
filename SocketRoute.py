import socket, threading, json, sys, time, os
from PySide2 import QtCore, QtWidgets

# qt user interface
class QtNode(QtWidgets.QWidget):
    def __init__(self, n: dict):
        super().__init__()
        self.thread = None
        self.nodes = n
        self.step = 0
        self.time = 0.0
        self.active = False

        # set main layout
        self.setWindowTitle("SocketRoute")
        self.layout = QtWidgets.QVBoxLayout(self)

        # scroll area
        scroll_area = QtWidgets.QScrollArea(self)
        scroll_area.setWidgetResizable(True)

        # table layouts
        scroll_widget = QtWidgets.QWidget()
        top_layout = QtWidgets.QVBoxLayout(scroll_widget)
        self.table = []

        # generate node tables
        keys_list = [str(key) for key in nodes.keys()]
        for key in range(1, keys_list.__len__() + 1):
            # add node label
            top_layout.addWidget(QtWidgets.QLabel("<b>Node %d</b>" % key))

            # generate table
            node_table = QtWidgets.QTableWidget(self)

            # set rows & cols
            node_table.setColumnCount(self.nodes.__len__())
            node_table.setRowCount(1)
            node_table.setHorizontalHeaderLabels(sorted(keys_list))
            node_table.setVerticalHeaderLabels(" ")

            # set values as -
            for col in range(node_table.columnCount()):
                node_table.setItem(0, col, QtWidgets.QTableWidgetItem("-"))

            # add to widget, and append.
            top_layout.addWidget(node_table)
            self.table.append(node_table)

        # add options
        self.auto = QtWidgets.QCheckBox("Run Without Intervention")
        bot_layout = QtWidgets.QVBoxLayout()
        bot_layout.addWidget(self.auto)

        # time
        sub_layout = QtWidgets.QHBoxLayout()
        self.timeLabel = QtWidgets.QLabel("<b>Step: %d</b>" % self.step)
        sub_layout.addWidget(self.timeLabel)
        sub_layout.addStretch(1)

        # button
        self.button = QtWidgets.QPushButton("Start", self)
        sub_layout.addWidget(self.button, alignment=QtCore.Qt.AlignBottom)

        # nest
        bot_layout.addLayout(sub_layout)
        scroll_area.setWidget(scroll_widget)
        self.layout.addWidget(scroll_area)
        self.layout.addLayout(bot_layout)

        # connect functions
        self.button.clicked.connect(self.on_start)

    def run_step(self):
        # update then send.
        for node in nodes.values():
            node.changed = False # reset change.

            # get table, then update with route table
            table = self.table[node.id - 1]
            rt = node.get_route_table()
            for col in range(table.columnCount()):
                if col + 1 not in rt: continue
                # get route value
                item = QtWidgets.QTableWidgetItem(str(rt[col + 1].get('cost', '-')))
                item.setFlags(item.flags() & ~QtCore.Qt.ItemIsEditable)
                table.setItem(0, col, item)

        for node in nodes.values():
            node.send()

    def run_indef(self):
        def run():
            # start timer
            start_time = time.time()

            while self.active:
                self.run_step()
                self.time = time.time() - start_time
                self.timeLabel.setText("<b>Time: %f seconds</b>" % self.time)
                # check if convergence
                if self.check_convergence() : break


            if self.check_convergence():
                self.button.setText("Done!")
                self.auto.stateChanged.disconnect()

        self.thread = threading.Thread(target=run)
        self.thread.start()

    def check_convergence(self):
        return all(not node.changed for node in self.nodes.values())


    def on_start(self):
        # connect new function
        self.auto.stateChanged.connect(self.toggle)
        self.button.clicked.disconnect()

        # check to run without interruptions
        if self.auto.isChecked():
            self.active = True
            self.run_indef()
        else:
            self.run_step()
            self.step += 1
            self.timeLabel.setText("<b>Step: %d</b>" % self.step)

            self.button.clicked.connect(self.on_click)
            self.button.setText("Next Step")


    def toggle(self, state):
        self.active = True if state == QtCore.Qt.Checked else False
        if self.active:
            self.run_indef()
            self.button.setText("Running...")
        else:
            self.button.setText("Next Step")


    def on_click(self):
        if not self.auto.isChecked():
            self.step += 1
            self.timeLabel.setText("<b>Step: %d</b>" % self.step)
            self.run_step()
            time.sleep(0.1) # delay for ui update. it'll mess with timing.

        # convergence
        if self.check_convergence():
            self.button.setText("Done!")
            self.auto.stateChanged.disconnect()
            self.button.clicked.disconnect()


# node class
class Node:
    def __init__(self, node_id: int, port: int, neighbors: dict):
        self.id = node_id
        self.route_table, self.neighbors = {}, {}
        self.route_table[self.id] = {'cost': 0, 'id': self.id} # set route to self as 0
        self.socket = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self.changed = False

        # lock to prevent race conditions
        self.table_lock = threading.Lock()

        # set neighbors and route
        self.add_neighbor(neighbors['id'], neighbors['cost'], neighbors['port'])

        # bind socket
        self.socket.bind(('localhost', port))
        self.port = port
        threading.Thread(target=self.listen).start()

    def get_route_table(self):
        with self.table_lock:
            return dict(self.route_table)

    def add_neighbor(self, neigh_id: int, neigh_cost: int, neigh_port: int) -> 'Node':
        self.neighbors[neigh_id] = {'cost': neigh_cost, 'port': neigh_port}

        # set default best route
        self.route_table[neigh_id] = {'cost': neigh_cost, 'id': neigh_id}

        return self

    def listen(self):
        while True:
            data, address = self.socket.recvfrom(1024)
            self.update_table(json.loads(data.decode()), address[1] - PORT)

    def update_table(self, node_info: dict, node_id: int):
        # find neighbors to send to
        with self.table_lock:
            for dest, info in node_info.items():
                dest = int(dest)
                if dest == self.id: continue # skip if id is self.id
                combined_dist = self.neighbors[node_id]['cost'] + info['cost']

                # if route is in table, check if shorter than stored path. assume default is inf
                if self.route_table.get(dest, {'cost': float('inf')})['cost'] > combined_dist:
                    self.route_table[dest] = {'cost': combined_dist}
                    self.changed = True

    def send(self):
        for neighbor, info in self.neighbors.items():
            neigh_port = info['port']

            # serialize and send to neighbors
            self.socket.sendto(json.dumps(self.route_table).encode(), ('localhost', neigh_port))


if __name__ == "__main__":
    PORT = 8000
    nodes = {}

    # get args
    path = sys.argv[1]

    # read file
    with open(path, 'r') as f:
        for line in f:
            node_a, node_b, cost = map(int, line.split()) # split (a b cost)
            # check if nodes exist
            port_a, port_b = PORT+node_a, PORT+node_b

            # check if node exists, if not then add
            node_a_neighbor = {
                'id': node_b,
                'cost': cost,
                'port': port_b
            }

            node_b_neighbor = {
                'id': node_a,
                'cost': cost,
                'port': port_a
            }

            nodes[node_a] = nodes[node_a].add_neighbor(*node_a_neighbor.values()) if node_a in nodes else \
                Node(node_a, port_a, node_a_neighbor)
            nodes[node_b] = nodes[node_b].add_neighbor(*node_b_neighbor.values()) if node_b in nodes else \
                Node(node_b, port_b, node_b_neighbor)

    # start qt ui
    app = QtWidgets.QApplication([])

    widget = QtNode(nodes)
    widget.resize(650, 650)
    widget.show()

    sys.exit(app.exec_())