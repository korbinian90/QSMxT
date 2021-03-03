#!/usr/bin/env python3

import os.path
import os
import glob
import fnmatch
import subprocess
from nipype.interfaces.fsl import BET, ImageMaths, ImageStats, MultiImageMaths, CopyGeom, Merge, UnaryMaths
from nipype.interfaces.utility import IdentityInterface, Function
from nipype.interfaces.io import DataSink, DataGrabber
from nipype.pipeline.engine import Workflow, Node, MapNode

from interfaces import nipype_interface_selectfiles as sf
from interfaces import nipype_interface_tgv_qsm as tgv
from interfaces import nipype_interface_phaseweights as phaseweights
from interfaces import nipype_interface_bestlinreg as bestlinreg
from interfaces import nipype_interface_makehomogeneous as makehomogeneous
from interfaces import nipype_interface_nonzeroaverage as nonzeroaverage
from interfaces import nipype_interface_composite as composite

import argparse


def create_qsm_workflow(
    session_dirs,
    bids_dir,
    work_dir,
    out_dir,
    bids_templates,
    masking,
    two_pass,
    add_bet,
    no_resampling,
    qsm_iterations,
    num_echoes_to_process,
    fractional_intensity,
    threshold,
    extra_fill_strength,
    homogeneity_filter,
    qsm_threads,
    qsub_account_string,
):

    # create initial workflow
    wf = Workflow(name='workflow_qsm', base_dir=work_dir)

    # datasink
    n_datasink = Node(
        interface=DataSink(base_directory=bids_dir, container=out_dir),
        name='datasink'
    )

    # iterate across subject list
    n_selectSessions = Node(
        interface=IdentityInterface(
            fields=['session_dir'],
        ),
        name="select_sessions"
    )
    n_selectSessions.iterables = ('session_dir', session_dirs)

    # iterate across subject list
    n_selectFiles = Node(
        interface=sf.SelectFiles(
            templates=bids_templates,
            num_files=num_echoes_to_process,
            base_directory = bids_dir
        ),
        iterfield='session_dir_p',
        name='select_files'
        # output: ['mag', 'phs', 'params']
    )
    wf.connect([
        (n_selectSessions, n_selectFiles, [('session_dir', 'session_dir_p')])
    ])

    # scale phase data
    def scale_to_pi(min_and_max):
        from math import pi

        min_value = min_and_max[0][0]
        max_value = min_and_max[0][1]
        fsl_cmd = ""

        # set range to [0, max-min]
        fsl_cmd += "-sub %.10f " % min_value
        max_value -= min_value
        min_value -= min_value

        # set range to [0, 2pi]
        fsl_cmd += "-div %.10f " % (max_value / (2*pi))

        # set range to [-pi, pi]
        fsl_cmd += "-sub %.10f" % pi
        return fsl_cmd

    mn_stats = MapNode(
        # -R : <min intensity> <max intensity>
        interface=ImageStats(op_string='-R'),
        iterfield=['in_file'],
        name='get_stats',
        # output: 'out_stat'
    )
    wf.connect([
        (n_selectFiles, mn_stats, [('phs', 'in_file')])
    ])

    mn_phase_scaled = MapNode(
        interface=ImageMaths(suffix="_scaled"),
        name='phase_scaled',
        iterfield=['in_file']
        # inputs: 'in_file', 'op_string'
        # output: 'out_file'
    )
    wf.connect([
        (n_selectFiles, mn_phase_scaled, [('phs', 'in_file')]),
        (mn_stats, mn_phase_scaled, [(('out_stat', scale_to_pi), 'op_string')])
    ])

    # read echotime and field strengths from json files
    def read_json(in_file):
        import os
        te = 0.001
        b0 = 7
        if os.path.exists(in_file):
            import json
            with open(in_file, 'rt') as fp:
                data = json.load(fp)
                te = data['EchoTime']
                b0 = data['MagneticFieldStrength']
        return te, b0

    mn_params = MapNode(
        interface=Function(
            input_names=['in_file'],
            output_names=['EchoTime', 'MagneticFieldStrength'],
            function=read_json
        ),
        iterfield=['in_file'],
        name='read_json'
    )
    wf.connect([
        (n_selectFiles, mn_params, [('params', 'in_file')])
    ])

    def repeat(in_file):
        return in_file


    # brain extraction
    mn_mask = MapNode(
        interface=Function(
            input_names=['in_file'],
            output_names=['mask_file'],
            function=repeat
        ),
        iterfield=['in_file'],
        name='repeat_mask'
    )

    if homogeneity_filter and ('bet' in masking or add_bet):
        mn_homogeneity_filter = MapNode(
            interface=makehomogeneous.MakeHomogeneousInterface(),
            iterfield=['in_file'],
            name='make_homogeneous'
            # output : out_file
        )
        wf.connect([
            (n_selectFiles, mn_homogeneity_filter, [('mag', 'in_file')])
        ])

    if 'bet' in masking or add_bet:
        mn_bet = MapNode(
            interface=BET(frac=fractional_intensity, mask=True, robust=True),
            iterfield=['in_file'],
            name='fsl_bet'
            # output: 'mask_file'
        )

        # homogeneity filter
        if homogeneity_filter:
            wf.connect([
                (mn_homogeneity_filter, mn_bet, [('out_file', 'in_file')])
            ])
        else:
            wf.connect([
                (n_selectFiles, mn_bet, [('mag', 'in_file')])
            ])

        if not add_bet:
            wf.connect([
                (mn_bet, mn_mask, [('mask_file', 'in_file')])
            ])
    if masking == 'phase-based':
        # per-echo phase-based masks
        mn_phaseweights = MapNode(
            interface=phaseweights.PhaseWeightsInterface(),
            iterfield=['in_file'],
            name='phase_weights'
            # output: 'out_file'
        )
        wf.connect([
            (mn_phase_scaled, mn_phaseweights, [('out_file', 'in_file')]),
        ])

        mn_phasemask = MapNode(
            interface=ImageMaths(
                suffix='_mask',
                op_string=f'-thrp {args.threshold} -bin -ero -dilM'
            ),
            iterfield=['in_file'],
            name='phase_mask'
            # input  : 'in_file'
            # output : 'out_file'
        )
        wf.connect([
            (mn_phaseweights, mn_phasemask, [('out_file', 'in_file')])
        ])
        
        wf.connect([
            (mn_phasemask, mn_mask, [('out_file', 'in_file')])
        ])
    elif masking == 'magnitude-based':
        # per-echo magnitude-based masks
        mn_magmask = MapNode(
            interface=ImageMaths(
                suffix="_mask",
                op_string=f"-thrp {args.threshold} -bin"
            ),
            iterfield=['in_file'],
            name='magnitude_mask'
            # output: 'out_file'
        )

        if homogeneity_filter:
            wf.connect([
                (mn_homogeneity_filter, mn_magmask, [('out_file', 'in_file')])
            ])
        else:
            wf.connect([
                (n_selectFiles, mn_magmask, [('mag', 'in_file')])
            ])

        wf.connect([
            (mn_magmask, mn_mask, [('out_file', 'in_file')])
        ])
    if two_pass or 'bet' in masking:
        # qsm processing
        mn_qsm_iterfield = ['phase_file', 'TE', 'b0']
        
        # if using a multi-echo masking method, add mask_file to iterfield
        if masking not in ['bet-firstecho', 'bet-lastecho']: mn_qsm_iterfield.append('mask_file')
        
        mn_qsm = MapNode(
            interface=tgv.QSMappingInterface(
                iterations=qsm_iterations,
                alpha=[0.0015, 0.0005],
                erosions=0 if masking in ['phase-based', 'magnitude-based'] else 5,
                num_threads=qsm_threads,
                out_suffix='_qsm',
                extra_arguments='--ignore-orientation --no-resampling' if no_resampling else ''
            ),
            iterfield=mn_qsm_iterfield,
            name='qsm'
            # output: 'out_file'
        )

        # args for PBS
        mn_qsm.plugin_args = {
            'qsub_args': f'-A {qsub_account_string} -q Short -l nodes=1:ppn={qsm_threads},mem=20gb,vmem=20gb,walltime=03:00:00',
            'overwrite': True
        }

        wf.connect([
            (mn_params, mn_qsm, [('EchoTime', 'TE')]),
            (mn_params, mn_qsm, [('MagneticFieldStrength', 'b0')]),
            (mn_mask, mn_qsm, [('mask_file', 'mask_file')]),
            (mn_phase_scaled, mn_qsm, [('out_file', 'phase_file')])
        ])

        # qsm averaging
        n_qsm_average = Node(
            interface=nonzeroaverage.NonzeroAverageInterface(),
            name='qsm_average'
            # input : in_files
            # output : out_file
        )
        wf.connect([
            (mn_qsm, n_qsm_average, [('out_file', 'in_files')])
        ])

        wf.connect([
            (n_qsm_average, n_datasink, [('out_file', 'qsm_average')]),
            (mn_qsm, n_datasink, [('out_file', 'qsms')]),
            (mn_mask, n_datasink, [('mask_file', 'masks')])
        ])
    if masking in ['phase-based', 'magnitude-based']:
        mn_mask_filled = MapNode(
            interface=ImageMaths(
                suffix='_fillh',
                op_string="-fillh" if not extra_fill_strength else " ".join(
                    ["-dilM" for f in range(extra_fill_strength)] 
                    + ["-fillh"] 
                    + ["-ero" for f in range(extra_fill_strength)]
                )
            ),
            iterfield=['in_file'],
            name='mask_filled'
        )

        if add_bet:
            mn_mask_plus_bet = MapNode(
                interface=composite.CompositeNiftiInterface(),
                name='mask_plus_bet',
                iterfield=['in_file1', 'in_file2'],
            )
            wf.connect([
                (mn_mask, mn_mask_plus_bet, [('mask_file', 'in_file1')]),
                (mn_bet, mn_mask_plus_bet, [('mask_file', 'in_file2')])
            ])
            wf.connect([
                (mn_mask_plus_bet, mn_mask_filled, [('out_file', 'in_file')])
            ])
        else:
            wf.connect([
                (mn_mask, mn_mask_filled, [('mask_file', 'in_file')])
            ])

        wf.connect([
            (mn_mask_filled, n_datasink, [('out_file', 'masks_filled')])
        ])

        mn_qsm_filled = MapNode(
            interface=tgv.QSMappingInterface(
                iterations=qsm_iterations,
                alpha=[0.0015, 0.0005],
                erosions=0,
                num_threads=qsm_threads,
                out_suffix='_qsm-filled',
                extra_arguments='--ignore-orientation --no-resampling' if no_resampling else ''
            ),
            iterfield=['phase_file', 'TE', 'b0', 'mask_file'],
            name='qsm_filledmask'
            # inputs: 'phase_file', 'TE', 'b0', 'mask_file'
            # output: 'out_file'
        )

        # args for PBS
        mn_qsm_filled.plugin_args = {
            'qsub_args': f'-A {qsub_account_string} -q Short -l nodes=1:ppn={qsm_threads},mem=20gb,vmem=20gb,walltime=03:00:00',
            'overwrite': True
        }

        wf.connect([
            (mn_params, mn_qsm_filled, [('EchoTime', 'TE')]),
            (mn_params, mn_qsm_filled, [('MagneticFieldStrength', 'b0')]),
            (mn_mask_filled, mn_qsm_filled, [('out_file', 'mask_file')]),
            (mn_phase_scaled, mn_qsm_filled, [('out_file', 'phase_file')]),
        ])
        wf.connect([
            (mn_qsm_filled, n_datasink, [('out_file', 'qsms_filled')]),
        ])

        # qsm averaging
        n_qsm_filled_average = Node(
            interface=nonzeroaverage.NonzeroAverageInterface(),
            name='qsm_filledmask_average'
            # input : in_files
            # output : out_file
        )
        wf.connect([
            (mn_qsm_filled, n_qsm_filled_average, [('out_file', 'in_files')])
        ])
        wf.connect([
            (n_qsm_filled_average, n_datasink, [('out_file', 'qsm_filled_average' if two_pass else 'qsm_final')])
        ])

        # composite qsm
        if two_pass:
            mn_qsm_composite = MapNode(
                interface=composite.CompositeNiftiInterface(),
                name='qsm_composite',
                iterfield=['in_file1', 'in_file2'],
            )
            wf.connect([
                (mn_qsm, mn_qsm_composite, [('out_file', 'in_file1')]),
                (mn_qsm_filled, mn_qsm_composite, [('out_file', 'in_file2')])
            ])

            n_qsm_composite_average = Node(
                interface=nonzeroaverage.NonzeroAverageInterface(),
                name='qsm_composite_average'
                # input : in_files
                # output: out_file
            )
            wf.connect([
                (mn_qsm_composite, n_qsm_composite_average, [('out_file', 'in_files')])
            ])

            wf.connect([
                (mn_qsm_composite, n_datasink, [('out_file', 'qsms_composite')]),
                (n_qsm_composite_average, n_datasink, [('out_file', 'qsm_final')]),
            ])

    return wf


if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="QSMxT qsm: QSM Reconstruction Pipeline",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter
    )

    parser.add_argument(
        'bids_dir',
        help='Input data folder that can be created using run_1_dicomToBids.py; can also use a ' +
             'custom folder containing subject folders and NIFTI files or a BIDS folder with a ' +
             'different structure, as long as --subject_folder_pattern, --session_folder_pattern, ' +
             '--input_magnitude_pattern and --input_phase_pattern are also specified.'
    )

    parser.add_argument(
        'out_dir',
        help='Output QSM folder; will be created if it does not exist.'
    )

    parser.add_argument(
        '--work_dir',
        default=None,
        help='NiPype working directory; defaults to \'work\' within \'out_dir\'.'
    )

    parser.add_argument(
        '--subject_folder_pattern',
        default='sub*',
        help='Pattern used to match subject folders in bids_dir'
    )

    parser.add_argument(
        '--session_folder_pattern',
        default='ses*',
        help='Pattern used to match session folders in subject folders'
    )

    parser.add_argument(
        '--input_magnitude_pattern',
        default='anat/*qsm*magnitude*nii*',
        help='Pattern to match magnitude files for qsm within subject folders.'
    )

    parser.add_argument(
        '--input_phase_pattern',
        default='anat/*qsm*phase*nii*',
        help='Pattern to match phase files for qsm within subject folders.'
    )

    parser.add_argument(
        '--subjects', '-s',
        default=None,
        nargs='*',
        help='List of subject folders to process; by default all subjects are processed.'
    )

    parser.add_argument(
        '--sessions',
        default=None,
        nargs='*',
        help='List of session folders to process; by default all sessions are processed.'
    )

    parser.add_argument(
        '--num_echoes', '-n',
        dest='num_echoes_to_process',
        default=None,
        type=int,
        help='The number of echoes to process; by default all echoes are processed.'
    )

    parser.add_argument(
        '--masking', '-m',
        default='magnitude-based',
        choices=['magnitude-based', 'phase-based', 'bet-multiecho', 'bet-firstecho', 'bet-lastecho'],
        help='Masking strategy. Magnitude-based and phase-based masking generates a mask by ' +
             'thresholding a lower percentage of the signal (adjust using the --threshold parameter). ' +
             'For phase-based masking, the spatial phase coherence is thresholded and the magnitude is ' +
             'not required. bet-multiecho uses a BET mask for each echo. bet-firstecho and bet-lastecho ' +
             'use a single BET mask for all echoes, generated using the magnitude image from the first ' +
             'echo and last echo only, respectively.'
    )

    parser.add_argument(
        '--two_pass',
        action='store_true',
        help='Use a two-pass QSM inversion, separating low and high-susceptibility structures for ' +
             'artefact reduction and doubling the runtime. Can only be applied to magnitude-based ' +
             'or phase-based masking.'
    )

    parser.add_argument(
        '--add_bet',
        action='store_true',
        help='Add a bet mask to the filled in threshold-based mask.'
    )

    parser.add_argument(
        '--no_resampling',
        action='store_true',
        help='Deactivate resampling inside TGV_QSM. Useful when resampling fails with error: ' +
             '\'Incompatible size of mask and data images\'. Check results carefully.'
    )

    parser.add_argument(
        '--iterations',
        type=int,
        default=1000,
        help='Number of iterations used for the dipole inversion step via tgv_qsm.'
    )

    parser.add_argument(
        '--homogeneity_filter', '-hf',
        action='store_true',
        help='Enables the magnitude homogeneity filter for magnitude-based and BET masking ' +
             'strategies.'
    )

    parser.add_argument(
        '--threshold', '-t',
        type=int,
        default=30,
        help='Threshold percentage used for magnitude-based and phase-based masking.'
    )

    parser.add_argument(
        '--fractional_intensity', '-fi',
        type=float,
        default=0.7,
        help='Fractional intensity for BET masking operations.'
    )

    def positive_int(value):
        ivalue = int(value)
        if ivalue <= 0:
            raise argparse.ArgumentTypeError("%s is an invalid positive int value" % value)
        return ivalue

    parser.add_argument(
        '--extra_fill_strength',
        type=positive_int,
        default=0,
        help='Adds strength to hole-filling for phase-based and magnitude-based masking; ' +
             'each integer increment adds to the masking procedure one further dilation step ' +
             'prior to hole-filling, followed by an equal number of erosion steps.'
    )

    parser.add_argument(
        '--pbs',
        default=None,
        dest='qsub_account_string',
        help='Run the pipeline via PBS and use the argument as the QSUB account string.'
    )

    parser.add_argument(
        '--debug',
        action='store_true',
        help='Enables some nipype settings for debugging.'
    )

    args = parser.parse_args()

    # environment variables and paths
    os.environ["FSLOUTPUTTYPE"] = "NIFTI_GZ"
    os.environ["PATH"] += os.pathsep + os.path.join(os.path.dirname(os.path.abspath(__file__)), "scripts")

    this_dir = os.path.dirname(os.path.abspath(__file__))
    if "PYTHONPATH" in os.environ: os.environ["PYTHONPATH"] += os.pathsep + this_dir
    else:                          os.environ["PYTHONPATH"]  = this_dir

    # debug options
    if args.debug:
        from nipype import config
        config.enable_debug_mode()
        config.set('execution', 'stop_on_first_crash', 'true')
        config.set('execution', 'remove_unnecessary_outputs', 'false')
        config.set('execution', 'keep_inputs', 'true')
        config.set('logging', 'workflow_level', 'DEBUG')
        config.set('logging', 'interface_level', 'DEBUG')
        config.set('logging', 'utils_level', 'DEBUG')

    # set default work_dir if needed
    if not args.work_dir: args.work_dir = args.out_dir

    # add_bet option only works with non-bet masking methods
    args.add_bet = args.add_bet and 'bet' not in args.masking

    # determine subject/session folders
    session_dirs = glob.glob(os.path.join(args.bids_dir, args.subject_folder_pattern, args.session_folder_pattern))
    if args.subjects:
        session_dirs = [x for x in session_dirs if any(s in x for s in args.subjects)]
    if args.sessions:
        session_dirs = [x for x in session_dirs if any(s in x for s in args.sessions)]
    session_dirs = [x.replace(os.path.relpath(args.bids_dir) + os.path.sep, '') for x in session_dirs]

    # determine file matching strings for n_selectFiles Node
    bids_templates = {
        'mag': os.path.join('{session_dir_p}', args.input_magnitude_pattern),
        'phs': os.path.join('{session_dir_p}', args.input_phase_pattern),
        'params': os.path.join('{session_dir_p}', args.input_phase_pattern.replace("nii.gz", "nii").replace("nii", "json"))
    }
    if 'echo' in args.masking:
        num_echoes = len(glob.glob(os.path.join(args.bids_dir, session_dirs[0], args.input_phase_pattern)))
        if 'bet-firstecho' in args.masking and num_echoes > 1:
            bids_templates['mag'] = bids_templates['mag'].replace('qsm*', 'qsm*E01*')
        if 'bet-lastecho' in args.masking and num_echoes > 1:
            bids_templates['mag'] = bids_templates['mag'].replace('qsm*', f'qsm*E{num_echoes:02}*')

    wf = create_qsm_workflow(
        session_dirs=session_dirs,
        bids_dir=os.path.abspath(args.bids_dir),
        work_dir=os.path.abspath(args.work_dir),
        out_dir=os.path.abspath(args.out_dir),
        bids_templates=bids_templates,
        masking=args.masking,
        two_pass=args.two_pass and 'bet' not in args.masking,
        add_bet=args.add_bet,
        no_resampling=args.no_resampling,
        qsm_iterations=args.iterations,
        num_echoes_to_process=args.num_echoes_to_process,
        fractional_intensity=args.fractional_intensity,
        threshold=args.threshold,
        extra_fill_strength=args.extra_fill_strength,
        homogeneity_filter=args.homogeneity_filter,
        qsm_threads=16 if args.qsub_account_string else 1,
        qsub_account_string=args.qsub_account_string
    )

    os.makedirs(os.path.abspath(args.work_dir), exist_ok=True)
    os.makedirs(os.path.abspath(args.out_dir), exist_ok=True)

    # make sure tgv_qsm is compiled on the target system before we start the pipeline:
    process = subprocess.run(['tgv_qsm'])

    # run workflow
    wf.write_graph(graph2use='flat', format='png', simple_form=False)
    if args.qsub_account_string:
        wf.run(
            plugin='PBSGraph',
            plugin_args={
                'qsub_args': f'-A {args.qsub_account_string} -q Short -l nodes=1:ppn=1,mem=5GB,vmem=5GB,walltime=00:30:00'
            }
        )
    else:
        wf.run(
            plugin='MultiProc',
            plugin_args={
                'n_procs': int(os.environ["NCPUS"]) if "NCPUS" in os.environ else int(os.cpu_count())
            }
        )

    #wf.run(plugin='PBS', plugin_args={f'-A {args.qsub_account_string} -l nodes=1:ppn=16,mem=5gb,vmem=5gb, walltime=30:00:00'})
