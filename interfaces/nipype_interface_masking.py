from nipype.interfaces.base import CommandLine, TraitedSpec, File, CommandLineInputSpec

class PbMaskingInputSpec(CommandLineInputSpec):
    phase = File(
        exists=True,
        mandatory=True,
        argstr="--phase %s"
    )
    mask = File(
        argstr="--output %s",
        name_source=['phase'],
        name_template='%s_pb_mask.nii'
    )

class PbMaskingOutputSpec(TraitedSpec):
    mask = File()

class PbMaskingInterface(CommandLine):
    input_spec = PbMaskingInputSpec
    output_spec = PbMaskingOutputSpec
    _cmd = "hagberg_pb_masking.jl"
