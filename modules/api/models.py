import inspect
from pydantic import BaseModel, Field, create_model
from typing import Any, Optional
from typing_extensions import Literal
from inflection import underscore
from modules.processing import StableDiffusionProcessingTxt2Img, StableDiffusionProcessingImg2Img
from modules.shared import sd_upscalers, opts, parser
from typing import Dict, List

API_NOT_ALLOWED = [
    "self",
    "kwargs",
    "sd_model",
    "outpath_samples",
    "outpath_grids",
    "sampler_index",
    "do_not_save_samples",
    "do_not_save_grid",
    "extra_generation_params",
    "overlay_images",
    "do_not_reload_embeddings",
    "seed_enable_extras",
    "prompt_for_display",
    "sampler_noise_scheduler_override",
    "ddim_discretize"
]

class ModelDef(BaseModel):
    """Assistance Class for Pydantic Dynamic Model Generation"""

    field: str
    field_alias: str
    field_type: Any
    field_value: Any
    field_exclude: bool = False


class PydanticModelGenerator:
    """
    Takes in created classes and stubs them out in a way FastAPI/Pydantic is happy about:
    source_data is a snapshot of the default values produced by the class
    params are the names of the actual keys required by __init__
    """

    def __init__(
        self,
        model_name: str = None,
        class_instance = None,
        additional_fields = None,
    ):
        def field_type_generator(k, v):
            # field_type = str if not overrides.get(k) else overrides[k]["type"]
            # print(k, v.annotation, v.default)
            field_type = v.annotation

            return Optional[field_type]

        def merge_class_params(class_):
            all_classes = list(filter(lambda x: x is not object, inspect.getmro(class_)))
            parameters = {}
            for classes in all_classes:
                parameters = {**parameters, **inspect.signature(classes.__init__).parameters}
            return parameters


        self._model_name = model_name
        self._class_data = merge_class_params(class_instance)

        self._model_def = [
            ModelDef(
                field=underscore(k),
                field_alias=k,
                field_type=field_type_generator(k, v),
                field_value=v.default
            )
            for (k,v) in self._class_data.items() if k not in API_NOT_ALLOWED
        ]

        for fields in additional_fields:
            self._model_def.append(ModelDef(
                field=underscore(fields["key"]),
                field_alias=fields["key"],
                field_type=fields["type"],
                field_value=fields["default"],
                field_exclude=fields["exclude"] if "exclude" in fields else False))

    def generate_model(self):
        """
        Creates a pydantic BaseModel
        from the json and overrides provided at initialization
        """
        fields = {
            d.field: (d.field_type, Field(default=d.field_value, alias=d.field_alias, exclude=d.field_exclude)) for d in self._model_def
        }
        DynamicModel = create_model(self._model_name, **fields)
        DynamicModel.__config__.allow_population_by_field_name = True
        DynamicModel.__config__.allow_mutation = True
        return DynamicModel

StableDiffusionTxt2ImgProcessingAPI = PydanticModelGenerator(
    "StableDiffusionProcessingTxt2Img",
    StableDiffusionProcessingTxt2Img,
    [{"key": "sampler_index", "type": str, "default": "Euler"}, {"key": "script_name", "type": str, "default": None}, {"key": "script_args", "type": list, "default": []}]
).generate_model()

StableDiffusionImg2ImgProcessingAPI = PydanticModelGenerator(
    "StableDiffusionProcessingImg2Img",
    StableDiffusionProcessingImg2Img,
    [{"key": "sampler_index", "type": str, "default": "Euler"}, {"key": "init_images", "type": list, "default": None}, {"key": "denoising_strength", "type": float, "default": 0.75}, {"key": "mask", "type": str, "default": None}, {"key": "include_init_images", "type": bool, "default": False, "exclude" : True}, {"key": "script_name", "type": str, "default": None}, {"key": "script_args", "type": list, "default": []}]
).generate_model()

class TextToImageResponse(BaseModel):
    images: List[str] = Field(default=None, title="Image", description="The generated image in base64 format.")
    parameters: dict
    info: str

class ImageToImageResponse(BaseModel):
    images: List[str] = Field(default=None, title="Image", description="The generated image in base64 format.")
    parameters: dict
    info: str

class ExtrasBaseRequest(BaseModel):
    resize_mode: Literal[0, 1] = Field(default=0, title="Resize Mode", description="Sets the resize mode: 0 to upscale by upscaling_resize amount, 1 to upscale up to upscaling_resize_h x upscaling_resize_w.")
    show_extras_results: bool = Field(default=True, title="Show results", description="Should the backend return the generated image?")
    gfpgan_visibility: float = Field(default=0, title="GFPGAN Visibility", ge=0, le=1, allow_inf_nan=False, description="Sets the visibility of GFPGAN, values should be between 0 and 1.")
    codeformer_visibility: float = Field(default=0, title="CodeFormer Visibility", ge=0, le=1, allow_inf_nan=False, description="Sets the visibility of CodeFormer, values should be between 0 and 1.")
    codeformer_weight: float = Field(default=0, title="CodeFormer Weight", ge=0, le=1, allow_inf_nan=False, description="Sets the weight of CodeFormer, values should be between 0 and 1.")
    upscaling_resize: float = Field(default=2, title="Upscaling Factor", ge=1, le=8, description="By how much to upscale the image, only used when resize_mode=0.")
    upscaling_resize_w: int = Field(default=512, title="Target Width", ge=1, description="Target width for the upscaler to hit. Only used when resize_mode=1.")
    upscaling_resize_h: int = Field(default=512, title="Target Height", ge=1, description="Target height for the upscaler to hit. Only used when resize_mode=1.")
    upscaling_crop: bool = Field(default=True, title="Crop to fit", description="Should the upscaler crop the image to fit in the chosen size?")
    upscaler_1: str = Field(default="None", title="Main upscaler", description=f"The name of the main upscaler to use, it has to be one of this list: {' , '.join([x.name for x in sd_upscalers])}")
    upscaler_2: str = Field(default="None", title="Secondary upscaler", description=f"The name of the secondary upscaler to use, it has to be one of this list: {' , '.join([x.name for x in sd_upscalers])}")
    extras_upscaler_2_visibility: float = Field(default=0, title="Secondary upscaler visibility", ge=0, le=1, allow_inf_nan=False, description="Sets the visibility of secondary upscaler, values should be between 0 and 1.")
    upscale_first: bool = Field(default=False, title="Upscale first", description="Should the upscaler run before restoring faces?")

class ExtraBaseResponse(BaseModel):
    html_info: str = Field(title="HTML info", description="A series of HTML tags containing the process info.")

class ExtrasSingleImageRequest(ExtrasBaseRequest):
    image: str = Field(default="", title="Image", description="Image to work on, must be a Base64 string containing the image's data.")

class ExtrasSingleImageResponse(ExtraBaseResponse):
    image: str = Field(default=None, title="Image", description="The generated image in base64 format.")

class FileData(BaseModel):
    data: str = Field(title="File data", description="Base64 representation of the file")
    name: str = Field(title="File name")

class ExtrasBatchImagesRequest(ExtrasBaseRequest):
    imageList: List[FileData] = Field(title="Images", description="List of images to work on. Must be Base64 strings")

class ExtrasBatchImagesResponse(ExtraBaseResponse):
    images: List[str] = Field(title="Images", description="The generated images in base64 format.")

class PNGInfoRequest(BaseModel):
    image: str = Field(title="Image", description="The base64 encoded PNG image")

class PNGInfoResponse(BaseModel):
    info: str = Field(title="Image info", description="A string with the parameters used to generate the image")
    items: dict = Field(title="Items", description="An object containing all the info the image had")

class ProgressRequest(BaseModel):
    skip_current_image: bool = Field(default=False, title="Skip current image", description="Skip current image serialization")

class ProgressResponse(BaseModel):
    progress: float = Field(title="Progress", description="The progress with a range of 0 to 1")
    eta_relative: float = Field(title="ETA in secs")
    state: dict = Field(title="State", description="The current state snapshot")
    current_image: str = Field(default=None, title="Current image", description="The current image in base64 format. opts.show_progress_every_n_steps is required for this to work.")
    textinfo: str = Field(default=None, title="Info text", description="Info text used by WebUI.")

class InterrogateRequest(BaseModel):
    image: str = Field(default="", title="Image", description="Image to work on, must be a Base64 string containing the image's data.")
    model: str = Field(default="clip", title="Model", description="The interrogate model used.")

class InterrogateResponse(BaseModel):
    caption: str = Field(default=None, title="Caption", description="The generated caption for the image.")

class TrainResponse(BaseModel):
    info: str = Field(title="Train info", description="Response string from train embedding or hypernetwork task.")

class CreateResponse(BaseModel):
    info: str = Field(title="Create info", description="Response string from create embedding or hypernetwork task.")

class PreprocessResponse(BaseModel):
    info: str = Field(title="Preprocess info", description="Response string from preprocessing task.")

fields = {}
for key, metadata in opts.data_labels.items():
    value = opts.data.get(key)
    optType = opts.typemap.get(type(metadata.default), type(value))

    if (metadata is not None):
        fields.update({key: (Optional[optType], Field(
            default=metadata.default ,description=metadata.label))})
    else:
        fields.update({key: (Optional[optType], Field())})

OptionsModel = create_model("Options", **fields)

flags = {}
_options = vars(parser)['_option_string_actions']
for key in _options:
    if(_options[key].dest != 'help'):
        flag = _options[key]
        _type = str
        if _options[key].default is not None: _type = type(_options[key].default)
        flags.update({flag.dest: (_type,Field(default=flag.default, description=flag.help))})

FlagsModel = create_model("Flags", **flags)

class SamplerItem(BaseModel):
    name: str = Field(title="Name")
    aliases: List[str] = Field(title="Aliases")
    options: Dict[str, str] = Field(title="Options")

class UpscalerItem(BaseModel):
    name: str = Field(title="Name")
    model_name: Optional[str] = Field(title="Model Name")
    model_path: Optional[str] = Field(title="Path")
    model_url: Optional[str] = Field(title="URL")
    scale: Optional[float] = Field(title="Scale")

class SDModelItem(BaseModel):
    title: str = Field(title="Title")
    model_name: str = Field(title="Model Name")
    hash: Optional[str] = Field(title="Short hash")
    sha256: Optional[str] = Field(title="sha256 hash")
    filename: str = Field(title="Filename")
    config: str = Field(title="Config file")

class HypernetworkItem(BaseModel):
    name: str = Field(title="Name")
    path: Optional[str] = Field(title="Path")

class FaceRestorerItem(BaseModel):
    name: str = Field(title="Name")
    cmd_dir: Optional[str] = Field(title="Path")

class RealesrganItem(BaseModel):
    name: str = Field(title="Name")
    path: Optional[str] = Field(title="Path")
    scale: Optional[int] = Field(title="Scale")

class PromptStyleItem(BaseModel):
    name: str = Field(title="Name")
    prompt: Optional[str] = Field(title="Prompt")
    negative_prompt: Optional[str] = Field(title="Negative Prompt")

class ArtistItem(BaseModel):
    name: str = Field(title="Name")
    score: float = Field(title="Score")
    category: str = Field(title="Category")

class EmbeddingItem(BaseModel):
    step: Optional[int] = Field(title="Step", description="The number of steps that were used to train this embedding, if available")
    sd_checkpoint: Optional[str] = Field(title="SD Checkpoint", description="The hash of the checkpoint this embedding was trained on, if available")
    sd_checkpoint_name: Optional[str] = Field(title="SD Checkpoint Name", description="The name of the checkpoint this embedding was trained on, if available. Note that this is the name that was used by the trainer; for a stable identifier, use `sd_checkpoint` instead")
    shape: int = Field(title="Shape", description="The length of each individual vector in the embedding")
    vectors: int = Field(title="Vectors", description="The number of vectors in the embedding")

class EmbeddingsResponse(BaseModel):
    loaded: Dict[str, EmbeddingItem] = Field(title="Loaded", description="Embeddings loaded for the current model")
    skipped: Dict[str, EmbeddingItem] = Field(title="Skipped", description="Embeddings skipped for the current model (likely due to architecture incompatibility)")

class MemoryResponse(BaseModel):
    ram: dict = Field(title="RAM", description="System memory stats")
    cuda: dict = Field(title="CUDA", description="nVidia CUDA memory stats")

class TrainEmbeddingAPI(BaseModel):
    embedding_name: str = Field(
        title="Embedding Name", description="Name of the embedding"
    )
    learn_rate: float = Field(
        title="Learning rate", description="Rate of learning", default=0.005
    )
    batch_size: int = Field(
        title="Batch size",
        description="How many images to create in a single batch",
        default=1,
    )
    gradient_step: int = Field(
        title="Gradient accumulation steps",
        description="Number of steps to accumulate the gradient",
        default=1,
    )
    data_root: str = Field(
        title="Dataset directory", description="Path to the directory with input images"
    )
    log_directory: str = Field(
        title="Log directory", description="", default="textual_inversion"
    )
    training_width: int = Field(title="Training width", description="", default=512)
    training_height: int = Field(title="Training height", description="", default=512)
    varsize: bool = Field(
        title="Do not resize images", description="Do not resize images", default=False
    )
    steps: int = Field(title="Max steps", description="", default=100000)
    clip_grad_mode: str = Field(
        title="Gradient clipping", description="Gradient clip mode", default="disabled"
    )
    clip_grad_value: float = Field(title="", description="", default=0.1)
    shuffle_tags: bool = Field(
        title="Shuffle tags",
        description="Shuffle tags by ',' when creating prompts",
        default=False,
    )
    tag_drop_out: bool = Field(
        title="Drop tags",
        description="Drop out tags when creating prompts",
        default=False,
    )
    latent_sampling_method: str = Field(
        title="Latent sampling method", description="", default="once"
    )
    create_image_every: int = Field(
        title="Create image every",
        description="Save an image to the log directory every N steps, 0 to disable",
        default=500,
    )
    save_embedding_every: int = Field(
        title="Save embedding",
        description="Save a copy of embedding to log directory every N steps, 0 to disable",
        default=500,
    )
    template_filename: str = Field(
        title="Prompt template",
        description="Prompt template file",
        default="style_filewords.txt",
    )
    save_image_with_stored_embedding: bool = Field(
        title="Save image with embedding",
        description="Save images with embedding in PNG chunks",
        default=True
    )
    preview_from_txt2img: bool = Field(
        title="Preview from txt2img",
        description="Read parameters (prompt, etc...) from txt2img tab when making previews",
        default=False,
    )
    preview_prompt: str = Field(title="Preview prompt", description="", default="")
    preview_negative_prompt: str = Field(
        title="Preview negative prompt", description="", default=""
    )
    preview_steps: int = Field(title="Preview steps", description="", default=20)
    preview_sampler_index: str = Field(
        title="Preview sampler", description="", default="Euler"
    )
    preview_cfg_scale: float = Field(
        title="Preview CFG scale", description="", default=7.0
    )
    preview_seed: float = Field(title="Preview seed", description="", default=-1.0)
    preview_width: int = Field(title="Preview width", description="", default=512)
    preview_height: int = Field(title="Preview height", description="", default=512)
    id_task: str = Field(title="ID Task", description="ID Task (unused)", default="")
