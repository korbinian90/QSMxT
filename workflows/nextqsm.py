from nipype.pipeline.engine import Workflow, Node, MapNode
from nipype.interfaces.utility import IdentityInterface
import interfaces.nipype_interface_nextqsm as nextqsm

def nextqsm_workflow(name='nextqsm'):
    wf = Workflow(name)
    
    inputnode = MapNode(
        interface=IdentityInterface(
            fields=['unwrapped_phase', 'mask', 'mag', 'TE', 'fieldStrength']),
        iterfield=['unwrapped_phase', 'mask', 'mag', 'TE', 'fieldStrength'],
        name='inputnode'
    )
    outputnode = MapNode(
        interface=IdentityInterface(
            fields=['qsm']),
        iterfield=['qsm'],
        name='outputnode'
    )
    
    mn_phase_normalize = MapNode(
        interface=nextqsm.NormalizeInterface(
            out_suffix='_normalized'
        ),
        iterfield=['phase', 'TE', 'fieldStrength'],
        name='normalize_phase'
        # output: 'out_file'
    )
    mn_qsm = MapNode(
        interface=nextqsm.NextqsmInterface(),
        iterfield=['phase', 'mask'],
        name='nextqsm'
        # output: 'out_file'
    )
    
    wf.connect([
        (inputnode, mn_phase_normalize, [('TE', 'TE'),
                                        ('fieldStrength', 'fieldStrength'),
                                        ('unwrapped_phase', 'phase')]),
        (inputnode, mn_qsm, [('mask', 'mask')]),
        (mn_phase_normalize, mn_qsm, [('out_file', 'phase')]),
        (mn_qsm, outputnode, [('out_file', 'qsm')]),
    ])

    return wf
