import random
import numpy
from threading import Lock
from seabreeze.spectrometers import list_devices, Spectrometer
import time
from textwrap import dedent
import dash
from dash import html, dcc
import dash_bootstrap_components as dbc
import plotly.graph_objs as go
import dash_daq as daq
from dash.dependencies import Input, Output, State

# abstract base class to represent spectrometers
class DashOceanOpticsSpectrometer:
    def __init__(self, specLock, commLock):
        self._spec = None                 # spectrometer
        self._specmodel = ''              # model name for graph title
        self._spectralData = [[], []]     # wavelengths and intensities
        self._controlFunctions = {}       # behaviour upon changing controls
        self._int_time_max = 1    # maximum integration time (ms)
        self._int_time_min = 0         # minimum integration time (ms)
        self.comm_lock = commLock         # for communicating with spectrometer
        self.spec_lock = specLock         # for editing spectrometer values

    # refreshes/populates spectrometer properties
    def assign_spec(self):
        return

    # get data for graph
    def get_spectrum(self):
        return self._spectralData

    # send each command; return successes and failures
    def send_control_values(self, commands):
        return ({}, {})

    # getter methods
    def model(self):
        return self._specmodel

    def int_time_max(self):
        return self._int_time_max

    def int_time_min(self):
        return self._int_time_min

# non-demo version
class PhysicalSpectrometer(DashOceanOpticsSpectrometer):

    def __init__(self, specLock, commLock):
        super().__init__(specLock, commLock)
        self.spec_lock.acquire()
        self.assign_spec()
        self.spec_lock.release()
        self._controlFunctions = {
            'integration-time-input':
            "self._spec.integration_time_micros",
        }

    def assign_spec(self):
        try:
            self.comm_lock.acquire()
            devices = list_devices()
            self._spec = Spectrometer(devices[0])
            self._specmodel = self._spec.model
            self._int_time_min = self._spec.integration_time_micros_limits[0]
            self._int_time_max = self._spec.integration_time_micros_limits[1]
        except Exception:
            pass
        finally:
            self.comm_lock.release()
            print('Spectrometer '+str(self._specmodel)+' connected with integration limits '+str(int(self._int_time_min))+' to '+str(int(self._int_time_max)))

    def get_spectrum(self):
        if self._spec is None:
            try:
                self.spec_lock.acquire()
                self.assign_spec()
            except Exception:
                pass
            finally:
                self.spec_lock.release()
        try:
            self.comm_lock.acquire()
            self._spectralData = self._spec.spectrum(correct_dark_counts=False,
                                                     correct_nonlinearity=True)
        except Exception:
            pass
        finally:
            self.comm_lock.release()

        return self._spectralData

    def send_control_values(self, commands):
        failed = {}
        succeeded = {}

        for ctrl_id in commands:
            try:
                self.comm_lock.acquire()
                eval(self._controlFunctions[ctrl_id])(commands[ctrl_id])
                succeeded[ctrl_id] = str(commands[ctrl_id])
            except Exception as e:
                failed[ctrl_id] = str(e).strip('b')
            finally:
                self.comm_lock.release()

        return(failed, succeeded)

    def model(self):
        self.spec_lock.acquire()
        self.assign_spec()
        self.spec_lock.release()
        return self._specmodel

    def int_time_max(self):
        self.spec_lock.acquire()
        self.assign_spec()
        self.spec_lock.release()
        return self._int_time_max

    def int_time_min(self):
        self.spec_lock.acquire()
        self.assign_spec()
        self.spec_lock.release()
        return self._int_time_min

class DemoSpectrometer(DashOceanOpticsSpectrometer):

    def __init__(self, specLock, commLock):
        super().__init__(specLock, commLock)
        try:
            self.spec_lock.acquire()
            self.assign_spec()
        except Exception:
            pass
        finally:
            self.spec_lock.release()
        self.controlFunctions = {
            'integration-time-input':
            "self.integration_time_demo",
        }
        self._sample_data_scale = self._int_time_min
        self._sample_data_add = 0

    def assign_spec(self):
        self._specmodel = "USB2000+"

    def get_spectrum(self, int_time_demo_val=1000):
        self._spectralData[0] = numpy.linspace(400, 900, 5000)
        self._spectralData[1] = [self.sample_spectrum(wl)
                                 for wl in self._spectralData[0]]
        return self._spectralData

    def send_control_values(self, commands):
        failed = {}
        succeeded = {}

        for ctrl_id in commands:
            try:
                eval(self.controlFunctions[ctrl_id])(commands[ctrl_id])
                succeeded[ctrl_id] = str(commands[ctrl_id])
            except Exception as e:
                failed[ctrl_id] = str(e)

        return(failed, succeeded)

    def model(self):
        return self._specmodel

    def int_time_max(self):
        return self._int_time_max

    def int_time_min(self):
        return self._int_time_min

    # demo-specific methods

    # generates a sample spectrum that's normally distributed about 500 nm
    def sample_spectrum(self, x):
        return (self._sample_data_scale * (numpy.e**(-1 * ((x-500) / 5)**2) +
                                           0.01 * random.random()) +
                self._sample_data_add * 10)

    def integration_time_demo(self, x):
        self._sample_data_scale = x

    def empty_control_demo(self, _):
        return
    
# class to represent all controls
class Control:
    def __init__(self, new_ctrl_id, new_ctrl_name,
                 new_component_type, new_component_attr):
        self.ctrl_id = new_ctrl_id                # id for callbacks
        self.ctrl_name = new_ctrl_name            # name for label
        self.component_type = new_component_type  # dash-daq component type
        self.component_attr = new_component_attr  # component attributes

    # creates a new control box with defined component, id, and name
    def create_ctrl_div(self, pwrOff):
        # create dash-daq components
        try:
            component_obj = getattr(daq, self.component_type)
        except AttributeError:
            component_obj = getattr(dcc, self.component_type)

        # disable if power is off
        self.component_attr['disabled'] = pwrOff
            
        component = component_obj(**self.component_attr)

        # generate html code
        new_control = html.Div(
            id=self.ctrl_id,
            children=[
                html.Div(
                    className='option-name',
                    children=[
                        self.ctrl_name
                    ]
                ),
                component
            ]
        )
        return new_control

    # gets whether we look for "value", "on", etc.
    def val_string(self):
        if('value' in self.component_attr):
            return 'value'
        elif('on' in self.component_attr):
            return 'on'

    # changes value ('on' or 'value', etc.)
    def update_value(self, new_value):
        self.component_attr[self.val_string()] = new_value

DEMO = False

#############################
# Spectrometer properties
#############################

# lock for modifying information about spectrometer
spec_lock = Lock()
# lock for communicating with spectrometer
comm_lock = Lock()

# initialize spec
spec = PhysicalSpectrometer(spec_lock, comm_lock)
spec.assign_spec()

############################
# Begin Dash app
############################

app = dash.Dash(external_stylesheets=[dbc.themes.BOOTSTRAP])
server = app.server

############################
# Style
############################

colors = {}

with open("colours.txt", 'r') as f:
    for line in f.readlines():
        colors[line.split(' ')[0]] = line.split(' ')[1].strip('\n')


############################
# All controls
############################

controls = []

# integration time, microseconds
int_time = Control('integration-time', "int. time (μs)",
                   "NumericInput",
                   {'id': 'integration-time-input',
                    'max': spec.int_time_max(),
                    'min': spec.int_time_min(),
                    'size': 150,
                    'value': spec.int_time_min()
                    }
                   )
controls.append(int_time)

############################
# Layout
############################

page_layout = [html.Div(id='page', children=[

    # plot
    html.Div(
        id='graph-container',
        children=[
            html.Div(
                children=[
                    html.Div(
                        id='graph-title',
                        children=[
                            "ocean optics"
                        ]
                    ),
                    dcc.Graph(id='spec-readings', animate=True),
                    dcc.Interval(
                        id='spec-reading-interval',
                        interval=1 * 1000,
                        n_intervals=0,
                        max_intervals=300 # stop after 5 mins.
                        # otherwise server has to handle callbacks for idle app
                    )
                ]
            )
        ]
    ),

    # power button
    html.Div(
        id='power-button-container',
        title='Turn the power on to begin viewing the data and controlling \
        the spectrometer.',
        children=[
            daq.PowerButton(
                id='power-button',
                size=50,
                color=colors['accent'],
                on=True if DEMO else False
            )
        ],
    ),

    # status box
    html.Div(
        id='status-box',
        children=[
            # autoscale
            html.Div(
                className='status-box-title',
                children=[
                    "autoscale plot"
                ]
            ),
            html.Div(
                id='autoscale-switch-container',
                title='Controls whether the plot automatically resizes \
                to fit the spectra.',
                children=[
                    daq.BooleanSwitch(
                        id='autoscale-switch',
                        on=True,
                        color=colors['accent']
                    )
                ]
            ),

            # submit button
            html.Div(
                id='submit-button-container',
                title='Sends all of the control values below the graph \
                to the spectrometer.',
                children=[
                    html.Button(
                        'update',
                        id='submit-button',
                        n_clicks=0,
                        n_clicks_timestamp=0
                    )
                ]
            ),

            # displays whether the parameters were successfully changed
            html.Div(
                id='submit-status',
                title='Contains information about the success or failure of your \
                commands.',
                children=[
                    ""
                ]
            )
        ]
    ),


    # all controls
    html.Div(
        id='controls',
        title='All of the spectrometer parameters that can be changed.',
        children=[
            ctrl.create_ctrl_div(True) for ctrl in controls
        ],
    ),

    # about the app
    html.Div(
        id='infobox',
        children=[
            html.Div(
                "about this app",
                id='infobox-title',
            ),
            dcc.Markdown(dedent('''
            This app enables you to take spectra and images using an Ocean
            Optics spectrometer and Thorlabs camera.
            '''))
        ]
    ),

])]

app.layout = html.Div(id='main', children=page_layout)


############################
# Callbacks
############################

# disable/enable the update button depending on whether options have changed
@app.callback(
    Output('submit-button', 'style'),
    [Input(ctrl.component_attr['id'], ctrl.val_string())
     for ctrl in controls] +
    [Input('submit-button', 'n_clicks_timestamp')]
)
def update_button_disable_enable(*args):
    now = time.time() * 1000
    disabled = {
        'color': colors['accent'],
        'backgroundColor': colors['background'],
        'cursor': 'not-allowed'
    }
    enabled = {
        'color': colors['background'],
        'backgroundColor': colors['accent'],
        'cursor': 'pointer'
    }

    # if the button was recently clicked (less than a second ago), then
    # it's safe to say that the callback was triggered by the button; so
    # we have to "disable" it
    if(int(now) - int(args[-1]) < 500 and int(args[-1]) > 0):
        return disabled
    else:
        return enabled


# spec model
@app.callback(
    Output('graph-title', 'children'),
    [Input('power-button', 'on')]
)
def update_spec_model(_):
    return "ocean optics %s" % spec.model()

# disable/enable controls
@app.callback(
    Output('controls', 'children'),
    [Input('power-button', 'on')]
)
def disable_enable_controls(pwr_on):
    return [ctrl.create_ctrl_div(not pwr_on) for ctrl in controls]

# send user-selected options to spectrometer
@app.callback(
    Output('submit-status', 'children'),
    [Input('submit-button', 'n_clicks')],
    [State(ctrl.component_attr['id'], ctrl.val_string())
        for ctrl in controls] + [
        State('power-button', 'on')
    ]
)
def update_spec_params(n_clicks, *args):

    # don't return anything if the device is off
    if(not args[-1]):
        return [
            "Press the power button to the top-right of the app, then \
            press the \"update\" button above to apply your options to \
            the spectrometer."
        ]

    # dictionary of commands; component id and associated value
    commands = {controls[i].component_attr['id']: args[i]
                for i in range(len(controls))}

    failed, succeeded = spec.send_control_values(commands)

    summary = []

    if len(failed) > 0:
        summary.append("The following parameters were not \
        successfully updated: ")
        summary.append(html.Br())
        summary.append(html.Br())

        for f in failed:
            # get the name as opposed to the id of each control
            # for readability
            [ctrlName] = [c.ctrl_name for c in controls
                          if c.component_attr['id'] == f]
            summary.append(ctrlName.upper() + ': ' + failed[f])
            summary.append(html.Br())

        summary.append(html.Br())
        summary.append(html.Hr())
        summary.append(html.Br())
        summary.append(html.Br())

    if len(succeeded) > 0:
        summary.append("The following parameters were successfully updated: ")
        summary.append(html.Br())
        summary.append(html.Br())

        for s in succeeded:
            [ctrlName] = [c.ctrl_name for c in controls
                          if c.component_attr['id'] == s]
            summary.append(ctrlName.upper() + ': ' + succeeded[s])
            summary.append(html.Br())

    return html.Div(summary)

# update the plot
@app.callback(
    Output('spec-readings', 'figure'),
    inputs=[
        Input('spec-reading-interval', 'n_intervals')
    ],
    state=[
        State('power-button', 'on'),
        State('autoscale-switch', 'on')
    ]
)
def update_plot(_, on, auto_range):

    traces = []
    wavelengths = []
    intensities = []

    x_axis = {
            'title': 'Wavelength (nm)',
            'titlefont': {
                'family': 'Helvetica, sans-serif',
                'color': colors['secondary']
            },
            'tickfont': {
                'color': colors['tertiary']
            },
            'dtick': 100,
            'color': colors['secondary'],
            'gridcolor': colors['grid-colour']
    }
    y_axis = {
        'title': 'Intensity (A.U.)',
        'titlefont': {
            'family': 'Helvetica, sans-serif',
            'color': colors['secondary']
        },
        'tickfont': {
            'color': colors['tertiary']
        },
        'color': colors['secondary'],
        'gridcolor': colors['grid-colour'],
    }

    if(on):
        spectrum = spec.get_spectrum()
        wavelengths = spectrum[0]
        intensities = spectrum[1]
    else:
        wavelengths = numpy.linspace(400, 900, 5000)
        intensities = [0 for wl in wavelengths]

    if(on):
        if(auto_range):
            x_axis['range'] = [
                min(wavelengths),
                max(wavelengths)
            ]
            y_axis['range'] = [
                min(intensities),
                max(intensities)
            ]
    traces.append(go.Scatter(
        x=wavelengths,
        y=intensities,
        name='Spectrometer readings',
        mode='lines',
        line={
            'width': 1,
            'color': colors['accent']
        }
    ))

    layout = go.Layout(
        height=600,
        font={
            'family': 'Helvetica Neue, sans-serif',
            'size': 12
        },
        margin={
            't': 20
        },
        titlefont={
            'family': 'Helvetica, sans-serif',
            'color': colors['primary'],
            'size': 26
        },
        xaxis=x_axis,
        yaxis=y_axis,
        paper_bgcolor=colors['background'],
        plot_bgcolor=colors['background'],
    )

    return {'data': traces,
            'layout': layout}

############################
# Run app
############################

if __name__ == '__main__':
    app.run_server(debug=True)
