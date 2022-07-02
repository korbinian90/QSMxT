from nipype.pipeline.engine import Workflow, MapNode, Node
from nipype.interfaces.utility import IdentityInterface
import interfaces.nipype_interface_romeo as romeo
import interfaces.nipype_interface_laplacian_unwrapping as laplacian_interface


def unwrapping_workflow(unwrapping='laplacian'):
    wf = Workflow(name=unwrapping + "_workflow")
    
    inputnode = MapNode(
        interface=IdentityInterface(fields=['wrapped_phase', 'mag']),
        iterfield=['wrapped_phase', 'mag'],
        name='inputnode')
    
    outputnode = MapNode(
        interface=IdentityInterface(fields=['unwrapped_phase']),
        iterfield=['unwrapped_phase'],
        name='outputnode')
    
    if unwrapping == "laplacian":
        laplacian = MapNode(
            interface=laplacian_interface.LaplacianInterface(),
            iterfield=['phase'],
            name='phase_unwrap_laplacian'
        )
        wf.connect([
            (inputnode, laplacian, [('wrapped_phase', 'phase')]),
            (laplacian, outputnode, [('out_file', 'unwrapped_phase')])
        ])        
        
    elif unwrapping == "romeo":
        romeo = MapNode(
            interface=romeo.RomeoInterface(),
            iterfield=['phase', 'mag'],
            name='phase_unwrap_romeo'
        )
        wf.connect([
            (inputnode, romeo, [('wrapped_phase', 'phase')]),
            (inputnode, romeo, [('mag', 'mag')]),
            (romeo, outputnode, [('out_file', 'unwrapped_phase')])
        ])
        
    return wf
